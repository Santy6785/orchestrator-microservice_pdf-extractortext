from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import re
import sys

from app.core.middleware import request_id_var

SERVICE_NAME = "orchestrator"

_LEVEL_ALIASES: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_AUTH_HEADER_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+)([^\s\"',;\}]+)"
)
_PDF_BYTES_RE = re.compile(r"(?:b['\"])?%PDF-[\s\S]*")


def sanitize_log_text(text: str) -> str:
    """Redact sensitive tokens, authorization headers, and raw PDF byte dumps."""
    if not text:
        return text
    sanitized = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    if "%PDF-" in sanitized:
        sanitized = _PDF_BYTES_RE.sub("[REDACTED_PDF_BYTES]", sanitized)
    return sanitized


class JsonLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects for container stdout."""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        raw_message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            raw_message = f"{raw_message}\n{record.exc_text}"

        safe_message = sanitize_log_text(raw_message)
        current_request_id = getattr(record, "request_id", None) or (
            request_id_var.get() or None
        )

        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "request_id": current_request_id,
            "message": safe_message,
        }
        return json.dumps(payload, ensure_ascii=False)


def resolve_log_level(level_value: str | None = None) -> int:
    """Resolve LOG_LEVEL supporting info, error, debug, warn, warning, critical."""
    raw = (level_value or os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    return _LEVEL_ALIASES.get(raw, logging.INFO)


def configure_logging(level_value: str | None = None) -> None:
    """Configure root logger to emit structured JSON logs to stdout."""
    level = resolve_log_level(level_value)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(JsonLogFormatter(service=SERVICE_NAME))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # Reduce noisy logs from third-party libraries while keeping JSON output
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers.clear()
    uvicorn_logger.propagate = True
    uvicorn_logger.setLevel(level)

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.propagate = True
    uvicorn_access.setLevel(level)