from typing import Any

import asyncio
import contextvars
import ipaddress
import logging
import time
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.status import HTTP_403_FORBIDDEN, HTTP_503_SERVICE_UNAVAILABLE

from app.core.trace import get_trace_recorder
from app.schemas.errors import ErrorResponse

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

# Estados del ciclo de vida del servicio.
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_SHUTTING_DOWN = "shutting_down"
STATE_STOPPED = "stopped"

# Transiciones válidas: estado_origen -> conjunto de estados destino permitidos.
_VALID_TRANSITIONS = {
    STATE_RUNNING: {STATE_PAUSED, STATE_SHUTTING_DOWN},
    STATE_PAUSED: {STATE_RUNNING, STATE_SHUTTING_DOWN},
    STATE_SHUTTING_DOWN: {STATE_STOPPED},
    STATE_STOPPED: set(),
}

_state = STATE_RUNNING
_state_lock = asyncio.Lock()
_active_requests = 0
_active_lock = asyncio.Lock()

# Rutas de control que deben estar protegidas por acceso interno.
_CONTROL_ROUTES = frozenset(
    {
        "/api/v1/control/trace",
        "/api/v1/control/metrics",
        "/api/v1/control/pause",
        "/api/v1/control/resume",
        "/api/v1/control/shutdown",
    }
)

# Hosts permitidos para acceso interno (loopback y TestClient).
_INTERNAL_HOSTS = frozenset(
    {"127.0.0.1", "::1", "localhost", "0.0.0.0", "testserver"}
)

# Cabecera opcional para token de control interno.
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"


async def pause_middleware(request: Request, call_next):
    global _active_requests

    if not request.url.path.startswith("/api/v1/control/"):
        state = _state
        if state == STATE_SHUTTING_DOWN:
            request_id = request.headers.get("X-Request-ID") or getattr(
                request.state, "request_id", None
            )
            return JSONResponse(
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                content=ErrorResponse(
                    detail="Servicio en proceso de apagado",
                    code="service_shutting_down",
                    request_id=request_id,
                ).model_dump(),
            )
        if state == STATE_PAUSED:
            request_id = request.headers.get("X-Request-ID") or getattr(
                request.state, "request_id", None
            )
            return JSONResponse(
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                content=ErrorResponse(
                    detail="Servicio temporalmente pausado",
                    code="service_paused",
                    request_id=request_id,
                ).model_dump(),
            )
        if state == STATE_STOPPED:
            request_id = request.headers.get("X-Request-ID") or getattr(
                request.state, "request_id", None
            )
            return JSONResponse(
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                content=ErrorResponse(
                    detail="Servicio detenido",
                    code="service_stopped",
                    request_id=request_id,
                ).model_dump(),
            )

        async with _active_lock:
            _active_requests += 1
        try:
            return await call_next(request)
        finally:
            async with _active_lock:
                _active_requests = max(0, _active_requests - 1)

    return await call_next(request)


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    request_id_var.set(request_id)
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


async def internal_access_middleware(request: Request, call_next):
    """Restringe el acceso a endpoints de control internos.

    Solo permite conexiones desde hosts loopback o que presenten el header
    ``X-Internal-Token`` con el valor configurado. Cuando no se configura
    ningún token (modo desarrollo), se permite el acceso desde cualquier host,
    asumiendo que el operador despliega en una red de confianza.

    Los demás reciben HTTP 403.
    """
    if request.url.path not in _CONTROL_ROUTES:
        return await call_next(request)

    expected_token = _get_internal_token()

    # Si no hay token configurado (modo desarrollo), permitir acceso.
    if expected_token is None:
        return await call_next(request)

    # Con token configurado, exigir token válido o host loopback.
    internal_token = request.headers.get(_INTERNAL_TOKEN_HEADER)
    token_ok = internal_token is not None and internal_token == expected_token

    if token_ok:
        return await call_next(request)

    client_host = request.client.host if request.client else ""
    is_loopback = client_host in _INTERNAL_HOSTS
    try:
        is_loopback = is_loopback or ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        pass

    if is_loopback:
        return await call_next(request)

    return JSONResponse(
        status_code=HTTP_403_FORBIDDEN,
        content=ErrorResponse(
            detail="Acceso restringido a endpoint interno",
            code="forbidden",
            request_id=getattr(request.state, "request_id", None),
        ).model_dump(),
    )


async def trace_capture_middleware(request: Request, call_next):
    """Captura metadata de request/response para el endpoint /trace.

    No almacena cuerpos de request/response, ni cabeceras sensibles.
    Excluye la propia ruta /trace para evitar recursividad.
    """
    if request.url.path == "/api/v1/control/trace":
        return await call_next(request)

    start_time = time.monotonic()
    request_id = getattr(request.state, "request_id", None) or request.headers.get(
        "X-Request-ID", ""
    )

    response: Response = await call_next(request)

    duration_ms = (time.monotonic() - start_time) * 1000.0

    entry = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "response_size_bytes": int(
            response.headers.get("content-length", 0) or 0
        ),
        "duration_ms": round(duration_ms, 2),
        "timestamp": time.time(),
        "headers": _redact_request_headers(request.headers),
        "query_params": dict(request.query_params),
        "downstream_calls": [],
    }

    recorder = get_trace_recorder()
    try:
        await recorder.record(entry)
    except RuntimeError:
        # No hay bucle de eventos activo.
        pass

    return response


_ENDPOINT_GROUPS_MW = (
    ("/api/v1/documents", "documents"),
    ("/api/v1/control", "control"),
)


def _endpoint_group_mw(path: str) -> str:
    for prefix, group in _ENDPOINT_GROUPS_MW:
        if path.startswith(prefix):
            return group
    return "other"


async def access_logging_middleware(request: Request, call_next):
    """Access logging estructurado por petición.

    Emite un JSON por request con method, path, status_code, duration_ms y
    request_id. No registra bodies, query params, headers sensibles ni
    contenido de PDF/texto extraído.
    """
    logger = logging.getLogger("app.access")

    start_time = time.monotonic()
    request_id = getattr(request.state, "request_id", None) or request.headers.get(
        "X-Request-ID", ""
    )

    try:
        response: Response = await call_next(request)
    except Exception:
        duration_ms = (time.monotonic() - start_time) * 1000.0
        logger.error(
            "request failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": round(duration_ms, 2),
            },
        )
        raise

    duration_ms = (time.monotonic() - start_time) * 1000.0
    logger.info(
        "request completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


async def metrics_middleware(request: Request, call_next):
    """Captura métricas HTTP de cada petición.

    Registra conteo de requests, grupo de código de estado, método, grupo de
    endpoint, latencia y errores. Excluye la propia ruta /metrics para no
    auto-contarse.
    """
    if request.url.path == "/api/v1/control/metrics":
        return await call_next(request)

    from app.core.metrics import get_metrics_collector as _get_metrics_collector

    collector = _get_metrics_collector()
    start_time = time.monotonic()

    await collector.increment_active_requests()
    try:
        response: Response = await call_next(request)
    finally:
        await collector.decrement_active_requests()

    duration_ms = (time.monotonic() - start_time) * 1000.0
    endpoint_group = _endpoint_group_mw(request.url.path)

    await collector.record_http_request(
        method=request.method,
        endpoint_group=endpoint_group,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    # Registrar errores (4xx/5xx) por separado.
    if response.status_code >= 400:
        error_code = f"http_{response.status_code}"
        service = None
        await collector.record_error(code=error_code, service=service)

    return response


def _redact_request_headers(headers: Any) -> dict[str, str]:
    """Devuelve cabeceras de request con sensibles omitidas."""
    redacted: dict[str, str] = {}
    if not headers:
        return redacted
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in _SENSITIVE_HEADERS:
            continue
        redacted[key_lower] = str(value)[:500]
    return redacted


_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "access-token",
        "refresh-token",
    }
)


def _get_internal_token() -> str | None:
    """Devuelve el token de control interno configurado, si existe."""
    from app.core.config import settings

    return settings.internal_control_token


async def _transition_state(new_state: str) -> bool:
    """Intenta transicionar el estado del servicio.

    Devuelve True si la transición se realizó, False si no es válida.
    Todas las mutaciones de estado pasan por este punto para evitar race
    conditions entre peticiones concurrentes.
    """
    global _state
    async with _state_lock:
        if new_state not in _VALID_TRANSITIONS.get(_state, set()):
            return False
        _state = new_state
        logging.getLogger(__name__).info(
            "Service state transition: %s -> %s", _state, new_state
        )
        return True


def get_state() -> str:
    """Devuelve el estado actual del servicio."""
    return _state


def is_paused() -> bool:
    """Devuelve True si el servicio está pausado o apagándose."""
    return _state in (STATE_PAUSED, STATE_SHUTTING_DOWN, STATE_STOPPED)


def is_shutting_down() -> bool:
    """Devuelve True si el servicio está apagándose o detenido."""
    return _state in (STATE_SHUTTING_DOWN, STATE_STOPPED)


async def set_pause(state: bool) -> bool:
    """Intenta pausar o reanudar el servicio.

    - state=True: RUNNING -> PAUSED (o PAUSED -> PAUSED, idempotente).
    - state=False: PAUSED -> RUNNING (o RUNNING -> RUNNING, idempotente).
    Rechaza transiciones desde SHUTTING_DOWN o STOPPED.
    Devuelve True si la operación se aceptó.
    """
    if state:
        if _state == STATE_PAUSED:
            return True  # idempotente
        return await _transition_state(STATE_PAUSED)
    else:
        if _state == STATE_RUNNING:
            return True  # idempotente
        return await _transition_state(STATE_RUNNING)


async def set_shutting_down(state: bool) -> bool:
    """Intenta iniciar o finalizar el apagado.

    - state=True: RUNNING/PAUSED -> SHUTTING_DOWN.
      Si ya está SHUTTING_DOWN, rechaza (duplicado → 409).
    - state=False: SHUTTING_DOWN -> STOPPED.
      Si ya está STOPPED, es idempotente.
    Devuelve True si la operación se aceptó.
    """
    if state:
        return await _transition_state(STATE_SHUTTING_DOWN)
    else:
        if _state == STATE_STOPPED:
            return True  # idempotente
        return await _transition_state(STATE_STOPPED)


async def increment_active_requests() -> None:
    async with _active_lock:
        global _active_requests
        _active_requests += 1


async def decrement_active_requests() -> None:
    async with _active_lock:
        global _active_requests
        _active_requests = max(0, _active_requests - 1)


def get_active_requests() -> int:
    return _active_requests