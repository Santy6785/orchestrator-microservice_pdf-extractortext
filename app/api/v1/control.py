import asyncio
import logging
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.core.config import settings
from app.core.trace import get_trace_recorder
from app.schemas.errors import ErrorResponse

from .control_impl import shutdown, pause, resume, metrics

router = APIRouter(prefix="/control", tags=["control"])

logger = logging.getLogger(__name__)

# Estados que indican que una dependencia downstream está disponible.
# Coinciden con las respuestas reales de los microservicios Extractor
# ({"status": "ok"}) y Persistencia ({"status": "ready"}).
_EXTRACTOR_HEALTHY_STATUSES = {"ok"}
_PERSISTENCE_HEALTHY_STATUSES = {"ready"}

# Timeout global para el chequeo de readiness (segundos).
HEALTH_GLOBAL_TIMEOUT_SECONDS = 5.0


async def _probe_health(client, path: str, healthy_statuses) -> str:
    """Consulta el health de una dependencia y devuelve su estado.

    Cualquier error de transporte, timeout o respuesta HTTP fallida (tras los
    reintentos de ``BaseClient``) se informa como ``"unreachable"``. Del mismo
    modo, una respuesta HTTP exitosa cuyo campo ``status`` no indique que la
    dependencia está lista también se informa como ``"unreachable"``.

    Cada llamada gestiona sus propias excepciones, de modo que el fallo de una
    dependencia no afecta al estado reportado de la otra.
    """
    try:
        response = await client.get(path)
        status = response.get("status") if isinstance(response, dict) else response
        if status in healthy_statuses:
            return str(status)
    except Exception as exc:
        logger.warning(
            "Health check failed for %s: %s",
            path,
            exc,
            exc_info=True,
        )
    return "unreachable"


async def _readiness_check() -> dict:
    """Ejecuta el chequeo de readiness con timeouts individuales y global.

    Cada dependencia se sondea en paralelo con su propio timeout individual
    (configurado en el cliente y acotado por ``asyncio.wait_for``). El
    conjunto completo está acotado por un timeout global para evitar
    bloqueos indefinidos. ``return_exceptions=True`` garantiza que el fallo
    de una dependencia no afecte el estado de la otra.
    """
    extractor = ExtractorClient(timeout=settings.health_timeout_seconds)
    persistence = PersistenceClient(timeout=settings.health_timeout_seconds)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                asyncio.wait_for(
                    _probe_health(
                        extractor, "/health", _EXTRACTOR_HEALTHY_STATUSES
                    ),
                    timeout=settings.health_timeout_seconds,
                ),
                asyncio.wait_for(
                    _probe_health(
                        persistence,
                        "/health/ready",
                        _PERSISTENCE_HEALTHY_STATUSES,
                    ),
                    timeout=settings.health_timeout_seconds,
                ),
                return_exceptions=True,
            ),
            timeout=HEALTH_GLOBAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        extractor_health = "unreachable"
        persistence_health = "unreachable"
    else:
        extractor_health = (
            results[0]
            if not isinstance(results[0], Exception)
            else "unreachable"
        )
        persistence_health = (
            results[1]
            if not isinstance(results[1], Exception)
            else "unreachable"
        )
    finally:
        await extractor.close()
        await persistence.close()

    extractor_available = extractor_health != "unreachable"
    persistence_available = persistence_health != "unreachable"

    status_code = (
        status.HTTP_200_OK
        if extractor_available and persistence_available
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return {
        "status_code": status_code,
        "content": {
            "orchestrator": "healthy",
            "extractor": extractor_health,
            "persistence": persistence_health,
        },
    }


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": dict},
    },
)
async def liveness(request: Request) -> JSONResponse:
    """Liveness check.

    Determina si el proceso del Orchestrator sigue funcionando. No realiza
    llamadas a servicios downstream, por lo que nunca falla por timeout de
    dependencias externas.

    - HTTP 200 cuando el proceso responde.
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"orchestrator": "alive"},
    )


@router.get(
    "/health/ready",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": dict},
        503: {"model": ErrorResponse},
    },
)
async def readiness(request: Request) -> JSONResponse:
    """Readiness check.

    Determina si el Orchestrator puede atender solicitudes que requieren sus
    dependencias (Extractor y Persistencia). Cada dependencia se verifica de
    forma independiente con timeout individual y el conjunto está acotado por
    un timeout global.

    - HTTP 200 cuando el orquestador y ambas dependencias están disponibles.
    - HTTP 503 cuando al menos una dependencia no responde o no está lista.
    """
    result = await _readiness_check()
    return JSONResponse(
        status_code=result["status_code"],
        content=result["content"],
    )


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": dict},
        503: {"model": ErrorResponse},
    },
)
async def health(request: Request) -> JSONResponse:
    """Health check compuesto (alias de readiness).

    Mantiene la ruta utilizada por los health checks de Docker y Traefik.
    Equivale a ``GET /health/ready``.
    """
    return await readiness(request)


router.include_router(shutdown)
router.include_router(pause)
router.include_router(resume)
router.include_router(metrics)


trace = APIRouter()


@trace.get(
    "/trace",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": dict},
        403: {"model": ErrorResponse},
    },
)
async def trace_endpoint(request: Request) -> JSONResponse:
    """Devuelve la última entrada de trace registrada.

    Solo contiene metadata segura: request_id, método, path, estado,
    tamaño de respuesta, duración, cabeceras sanitizadas (sin Authorization),
    query params (sin claves sensibles) y llamadas downstream resumidas.
    Nunca incluye cuerpos de PDF, texto extraído, tokens ni secretos.

    - HTTP 200 con la última entrada de trace, o un objeto vacío si no hay
      ninguna registrada.
    - HTTP 403 si el acceso no es desde un host interno o no presenta el
      token de control interno.
    """
    recorder = get_trace_recorder()
    latest = await recorder.get_latest()

    if latest is None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "trace": None,
                "message": "No hay traces registrados aún.",
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"trace": latest},
    )


router.include_router(trace)
