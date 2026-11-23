import asyncio
import logging
from typing import Any

import httpx

from app.core.middleware import request_id_var

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF = (0.2, 0.5, 1.0)

# Códigos de estado que solo se reintentan en métodos idempotentes (GET/DELETE).
RETRYABLE_STATUS_CODES = (502, 503, 504)

# Errores de transporte previos a enviar el cuerpo: los únicos reintentables
# en métodos no idempotentes (POST, PUT, PATCH, ...).
WRITE_SIDE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


class BaseClient:
    """Base HTTP client with retry, timeout and request‑ID propagation.

    Política de reintentos (``_request``):
    * ``GET`` y ``DELETE``: se reintentan errores de transporte
      (``httpx.TransportError``, incluido ``TimeoutException``) y respuestas
      ``502``/``503``/``504``.
    * ``POST`` y cualquier otro método: solo se reintentan
      ``httpx.ConnectError``, ``httpx.ConnectTimeout`` y
      ``httpx.PoolTimeout`` (fallos antes de enviar el cuerpo). Nunca por
      código de estado, ni ante ``ReadTimeout``, ``WriteError``,
      ``ReadError`` o ``RemoteProtocolError``.
    * Nunca se reintentan ``4xx``.
    * Se intentan como máximo ``MAX_ATTEMPTS`` veces en total (incluido el
      primero), esperando ``BACKOFF[k-1]`` segundos antes del reintento k.
    * ``raise_for_status()`` se ejecuta FUERA del bucle de reintentos y fuera
      de cualquier ``try``. Si se agotan los intentos con una última respuesta
      ``502/503/504`` se lanza ``httpx.HTTPStatusError`` con esa respuesta;
      si se agotan por errores de transporte, se propaga la excepción de
      transporte que ven hoy los llamadores.
    """

    def __init__(self, service_url: str, timeout: float = 5.0):
        self.timeout = timeout
        self.service_url = service_url
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.service_url}{path}"
        headers = kwargs.pop("headers", {})
        # Propagate request‑ID from contextvar if present
        request_id = request_id_var.get()
        if request_id:
            headers["X-Request-ID"] = request_id

        idempotent = method.upper() in ("GET", "DELETE")

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._client.request(
                    method, url, headers=headers, **kwargs
                )
            except httpx.TransportError as exc:
                # GET/DELETE reintentan cualquier error de transporte;
                # POST y el resto solo fallos antes de enviar el cuerpo.
                retryable = idempotent or isinstance(exc, WRITE_SIDE_TRANSPORT_ERRORS)
                if not retryable or attempt == MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "%s request to %s failed on attempt %d/%d: %s",
                    method,
                    url,
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                )
                await asyncio.sleep(BACKOFF[attempt - 1])
                continue

            # Solo GET/DELETE reintentan 502/503/504, y solo mientras queden
            # intentos. En el último intento la respuesta se deja para
            # raise_for_status() abajo.
            if (
                idempotent
                and response.status_code in RETRYABLE_STATUS_CODES
                and attempt < MAX_ATTEMPTS
            ):
                logger.warning(
                    "%s request to %s failed on attempt %d/%d: HTTP %d",
                    method,
                    url,
                    attempt,
                    MAX_ATTEMPTS,
                    response.status_code,
                )
                await asyncio.sleep(BACKOFF[attempt - 1])
                continue
            break

        # raise_for_status() va FUERA del bucle y fuera de cualquier try de
        # reintento. HTTPStatusError (incluido 4xx) se propaga aquí.
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            if not response.content:
                # Cuerpo vacío (p. ej. 200/204 con Content-Type JSON): no hay
                # nada que decodificar; se devuelve el texto vacío en lugar de
                # llamar response.json() y provocar JSONDecodeError.
                return response.text
            return response.json()
        return response.text

    async def get(self, path: str, **kwargs) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(
        self, path: str, json: dict[str, Any] | None = None, **kwargs
    ) -> Any:
        return await self._request("POST", path, json=json, **kwargs)

    async def delete(self, path: str, **kwargs) -> Any:
        return await self._request("DELETE", path, **kwargs)

    async def close(self):
        await self._client.aclose()
