"""Registro de traces de request/response para el endpoint /trace.

Almacena en memoria (por instancia de proceso) metadata segura de los últimos
request/response vistos. Nunca guarda cuerpos de PDF, texto extraído,
cabeceras de autenticación, tokens, secretos ni datos personales sensibles.

La estructura es un ``collections.deque`` con ``maxlen`` acotado para evitar
crecimiento ilimitado de memoria. Las escrituras están protegidas por un
``asyncio.Lock`` para evitar race conditions ante requests concurrentes.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

# Número máximo de entradas de trace retenidas en memoria (por instancia).
MAX_TRACE_ENTRIES = 100

# Longitud máxima permitida para cualquier campo de texto almacenado.
MAX_FIELD_LENGTH = 500

# Cabeceras que nunca se almacenan (incluso redactadas).
SENSITIVE_HEADERS = frozenset(
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

# Nombres de query params que nunca se almacenan (incluso redactados).
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "session",
        "session_id",
    }
)


def _truncate(value: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    """Trunca un texto si excede la longitud máxima permitida."""
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def _sanitize(text: str) -> str:
    """Aplica redacción de datos sensibles (mismos patrones que logging.py)."""
    from app.core.logging import sanitize_log_text

    return sanitize_log_text(text)


def _redact_headers(headers: Any) -> dict[str, str]:
    """Devuelve un diccionario de cabeceras con sensibles omitidas y el resto
    sanitizado y truncado."""
    redacted: dict[str, str] = {}
    if not headers:
        return redacted
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in SENSITIVE_HEADERS:
            continue
        safe_value = _truncate(_sanitize(str(value)))
        redacted[key_lower] = safe_value
    return redacted


def _redact_query_params(query_params: Any) -> dict[str, str]:
    """Devuelve query params con claves sensibles omitidas y valores
    sanitizados/truncados."""
    redacted: dict[str, str] = {}
    if not query_params:
        return redacted
    for key, value in query_params.items():
        key_lower = key.lower()
        if key_lower in SENSITIVE_QUERY_KEYS:
            continue
        safe_value = _truncate(_sanitize(str(value)))
        redacted[key_lower] = safe_value
    return redacted


def redact_trace_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Aplica redacción defensiva a una entrada de trace antes de almacenarla.

    Elimina campos que pudieran contener información sensible y trunca los
    demás para controlar el tamaño de almacenamiento.
    """
    safe_entry: dict[str, Any] = {
        "request_id": entry.get("request_id"),
        "method": entry.get("method"),
        "path": _truncate(str(entry.get("path", ""))),
        "status_code": entry.get("status_code"),
        "response_size_bytes": entry.get("response_size_bytes"),
        "duration_ms": entry.get("duration_ms"),
        "timestamp": entry.get("timestamp"),
        "headers": _redact_headers(entry.get("headers")),
        "query_params": _redact_query_params(entry.get("query_params")),
        "downstream_calls": entry.get("downstream_calls", []),
    }
    return safe_entry


class TraceRecorder:
    """Registra y recupera traces de request/response en memoria.

    Thread-safe mediante ``asyncio.Lock``. La retención está acotada por
    ``MAX_TRACE_ENTRIES``.
    """

    def __init__(self, max_entries: int = MAX_TRACE_ENTRIES) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = asyncio.Lock()

    async def record(self, entry: dict[str, Any]) -> None:
        """Almacena una entrada de trace tras aplicarle redacción defensiva."""
        safe_entry = redact_trace_entry(entry)
        async with self._lock:
            self._entries.append(safe_entry)

    async def get_latest(self) -> dict[str, Any] | None:
        """Devuelve la última entrada de trace, o None si no hay ninguna."""
        async with self._lock:
            if not self._entries:
                return None
            return dict(self._entries[-1])

    async def get_all(self) -> list[dict[str, Any]]:
        """Devuelve todas las entradas de trace (más reciente al final)."""
        async with self._lock:
            return [dict(e) for e in self._entries]

    async def clear(self) -> None:
        """Elimina todas las entradas de trace."""
        async with self._lock:
            self._entries.clear()


# Única instancia compartida del grabador de traces.
trace_recorder = TraceRecorder()


def get_trace_recorder() -> TraceRecorder:
    """Devuelve la instancia compartida de TraceRecorder."""
    return trace_recorder
