from __future__ import annotations

from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.core.middleware import request_id_var
from app.schemas.errors import ErrorResponse


class DownstreamService:
    """Identificadores de los microservicios downstream del orquestador."""

    EXTRACTOR = "extractor"
    PERSISTENCE = "persistence"


class DownstreamErrorTranslator:
    """Traduce errores de ``httpx`` provenientes de los microservicios
    Extractor y Persistencia a :class:`fastapi.HTTPException` con el
    contrato uniforme de errores (issue O-16 / D7).

    El cuerpo de error sigue el esquema::

        {
          "detail": "...",
          "code": "...",
          "request_id": "..."
    }

    El ``request_id`` se obtiene del contexto de la petición actual
    (propagado por el middleware mediante la cabecera ``X-Request-ID``).

    Diferencia claramente los errores del Extractor de los de Persistencia y
    no aplica una traducción genérica a ambos servicios.
    """

    # ------------------------------------------------------------------
    # Códigos de error para Persistencia (según matriz O-16)
    # ------------------------------------------------------------------
    _PERSISTENCE_STATUS_CODES = {
        404: (status.HTTP_404_NOT_FOUND, "persistence_not_found"),
        409: (status.HTTP_409_CONFLICT, "persistence_conflict"),
        413: (
            status.HTTP_413_CONTENT_TOO_LARGE,
            "persistence_payload_too_large",
        ),
        422: (status.HTTP_422_UNPROCESSABLE_CONTENT, "persistence_unprocessable"),
    }

    # ------------------------------------------------------------------
    # Códigos de error para Extractor (según matriz O-16)
    # ------------------------------------------------------------------
    _EXTRACTOR_STATUS_CODES = {
        400: (status.HTTP_422_UNPROCESSABLE_CONTENT, "extractor_unprocessable"),
        422: (status.HTTP_422_UNPROCESSABLE_CONTENT, "extractor_unprocessable"),
        429: (status.HTTP_429_TOO_MANY_REQUESTS, "extractor_too_many_requests"),
    }

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    @classmethod
    def _get_request_id(cls) -> Optional[str]:
        """Devuelve el request_id del contexto actual, si existe."""
        value = request_id_var.get()
        return value or None

    @classmethod
    def _build_http_exception(
        cls,
        status_code: int,
        code: str,
        message: str,
        existing_id: Optional[str] = None,
    ) -> HTTPException:
        """Construye una HTTPException con el cuerpo de error uniforme."""
        return HTTPException(
            status_code=status_code,
            detail=ErrorResponse(
                detail=message,
                code=code,
                request_id=cls._get_request_id(),
                existing_id=existing_id,
            ).model_dump(),
        )

    @classmethod
    def _extract_existing_id(cls, response: httpx.Response) -> Optional[str]:
        """Extrae el identificador del documento duplicado desde el cuerpo de
        una respuesta de error, de forma segura (sin lanzar si el cuerpo no es
        JSON o no contiene el campo esperado)."""
        try:
            body = response.json()
        except Exception:
            return None
        if isinstance(body, dict):
            return body.get("id") or body.get("existing_id")
        return None

    # ------------------------------------------------------------------
    # Traducción de errores de estado HTTP (HTTPStatusError)
    # ------------------------------------------------------------------

    @classmethod
    def translate_persistence_status_error(
        cls, exc: httpx.HTTPStatusError
    ) -> HTTPException:
        """Traduce un HTTPStatusError de Persistencia según la matriz O-16.

        - 404 → 404
        - 409 → 409 (conserva existing_id si el downstream lo provee)
        - 413 → 413
        - 422 → 422
        - 5xx   → 502
        - Cualquier otro → 502
        """
        status_code = exc.response.status_code

        if status_code in cls._PERSISTENCE_STATUS_CODES:
            mapped_status, code = cls._PERSISTENCE_STATUS_CODES[status_code]
            existing_id: Optional[str] = None
            if status_code == 409:
                existing_id = cls._extract_existing_id(exc.response)
            message = cls._persistence_message(status_code)
            return cls._build_http_exception(
                mapped_status, code, message, existing_id=existing_id
            )

        # 5xx y cualquier otro estado → 502 Bad Gateway
        return cls._build_http_exception(
            status.HTTP_502_BAD_GATEWAY,
            "persistence_error",
            "Error comunicando con el servicio de persistencia",
        )

    @classmethod
    def translate_extractor_status_error(
        cls, exc: httpx.HTTPStatusError
    ) -> HTTPException:
        """Traduce un HTTPStatusError del Extractor según la matriz O-16.

        - 400 → 422
        - 422 → 422
        - 429 → 429
        - 5xx → 502
        - Cualquier otro → 502
        """
        status_code = exc.response.status_code

        if status_code in cls._EXTRACTOR_STATUS_CODES:
            mapped_status, code = cls._EXTRACTOR_STATUS_CODES[status_code]
            return cls._build_http_exception(
                mapped_status, code, cls._extractor_message(status_code)
            )

        # 5xx y cualquier otro estado → 502 Bad Gateway
        return cls._build_http_exception(
            status.HTTP_502_BAD_GATEWAY,
            "extractor_error",
            "Error comunicando con el servicio extractor",
        )

    # ------------------------------------------------------------------
    # Traducción de errores de comunicación (RequestError)
    # ------------------------------------------------------------------

    @classmethod
    def translate_communication_error(
        cls, exc: httpx.RequestError, service: str
    ) -> HTTPException:
        """Traduce errores de transporte (timeout y conexión) a HTTP 503.

        ``httpx.TimeoutException`` (incluido ``ReadTimeout``,
        ``ConnectTimeout``, etc.) es una subclase de
        ``httpx.RequestError``; se identifica explícitamente para reportar
        un código de timeout. Los errores de conexión (p. ej.
        ``httpx.ConnectError``) se reportan como error de conexión. Ambos
        devuelven HTTP 503, nunca 502.
        """
        if isinstance(exc, httpx.TimeoutException):
            code = f"{service}_timeout"
            message = f"Tiempo de espera agotado en el servicio {service}"
        else:
            code = f"{service}_connection_error"
            message = f"Error de conexión con el servicio {service}"

        return cls._build_http_exception(
            status.HTTP_503_SERVICE_UNAVAILABLE, code, message
        )

    # ------------------------------------------------------------------
    # Traducción de excepciones inesperadas (no httpx)
    # ------------------------------------------------------------------

    @classmethod
    def translate_unexpected_error(
        cls, service: str
    ) -> HTTPException:
        """Traduce una excepción no-httpx ocurrida al llamar a un servicio
        downstream como un error de comunicación genérico (HTTP 502).

        Esto se reserva para excepciones que no son ni HTTPStatusError ni
        RequestError (p. ej. ``RuntimeError``). No se expone el mensaje
        original para no filtrar información interna.
        """
        return cls._build_http_exception(
            status.HTTP_502_BAD_GATEWAY,
            f"{service}_error",
            f"Error comunicando con el servicio {service}",
        )

    # ------------------------------------------------------------------
    # Mensajes legibles (sin detalles internos)
    # ------------------------------------------------------------------

    @staticmethod
    def _persistence_message(status_code: int) -> str:
        return {
            404: "Documento no encontrado en el servicio de persistencia",
            409: "Documento duplicado en el servicio de persistencia",
            413: "El documento excede el tamaño permitido en persistencia",
            422: "Error de validación en el servicio de persistencia",
        }[status_code]

    @staticmethod
    def _extractor_message(status_code: int) -> str:
        return {
            400: "Error de validación en el servicio extractor",
            422: "Error de validación en el servicio extractor",
            429: "Demasiadas solicitudes al servicio extractor",
        }[status_code]
