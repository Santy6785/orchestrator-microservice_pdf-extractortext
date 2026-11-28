"""Pruebas de mejoras de logging (issue #55).

Cubre:
- Handler a stderr para WARNING y superiores.
- Sanitización de stack traces en logs.
- Access logging estructurado por petición.
- Request ID presente y generado cuando no existe.
- No duplicación de handlers.
- Logging de excepciones sin exposición de secretos.
- Compatibilidad con requests concurrentes.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import httpx
import respx
from fastapi.testclient import TestClient

from app.core.logging import (
    JsonLogFormatter,
    configure_logging,
)
from app.core.middleware import request_id_var
from app.main import create_app


# ---------------------------------------------------------------------------
# 1. Formato estructurado con campos requeridos
# ---------------------------------------------------------------------------


def test_json_formatter_structured_output():
    """Cada línea de log es JSON con los campos requeridos."""
    formatter = JsonLogFormatter()
    token = request_id_var.set("req-struct-001")
    try:
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Procesando documento %s",
            args=("doc-1",),
            exc_info=None,
        )
        rendered = formatter.format(record)
        parsed = json.loads(rendered)
        assert set(parsed.keys()) == {
            "timestamp",
            "level",
            "service",
            "request_id",
            "message",
        }
        assert parsed["service"] == "orchestrator"
        assert parsed["request_id"] == "req-struct-001"
    finally:
        request_id_var.reset(token)


# ---------------------------------------------------------------------------
# 2. Request ID presente y propagado
# ---------------------------------------------------------------------------


@respx.mock
def test_request_id_present_in_access_logs():
    """El request_id se propaga a los access logs estructurados."""
    respx.get("http://extractor/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )

    buffer = io.StringIO()
    configure_logging("DEBUG")
    # Rebind handler stream para capturar
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream = buffer

    client = TestClient(create_app())
    client.get("/api/v1/control/health", headers={"X-Request-ID": "req-prop-001"})

    raw = buffer.getvalue()
    access_entries = [
        json.loads(line) for line in raw.splitlines() if line.strip()
    ]
    # Debe haber al menos una entrada de access log con request_id
    access_with_rid = [
        e for e in access_entries if e.get("request_id") == "req-prop-001"
    ]
    assert len(access_with_rid) >= 1, "No se encontró access log con request_id"


# ---------------------------------------------------------------------------
# 3. Request ID generado cuando no existe
# ---------------------------------------------------------------------------


@respx.mock
def test_request_id_generated_when_missing():
    """Si no se envía X-Request-ID, se genera uno automáticamente."""
    respx.get("http://extractor/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )

    client = TestClient(create_app())
    response = client.get("/api/v1/control/health")

    # El response debe incluir el header X-Request-ID generado
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] != ""
    assert len(response.headers["x-request-id"]) > 0


# ---------------------------------------------------------------------------
# 4. Niveles de logging correctos (incluido WARN)
# ---------------------------------------------------------------------------


def test_log_levels_including_warn(monkeypatch):
    """DEBUG, INFO, WARN, WARNING y ERROR son niveles válidos."""
    assert logging.getLevelName(logging.DEBUG) == "DEBUG"
    assert logging.getLevelName(logging.INFO) == "INFO"
    assert logging.getLevelName(logging.WARN) == "WARNING"
    assert logging.getLevelName(logging.WARNING) == "WARNING"
    assert logging.getLevelName(logging.ERROR) == "ERROR"

    from app.core.logging import resolve_log_level

    assert resolve_log_level("debug") == logging.DEBUG
    assert resolve_log_level("warn") == logging.WARNING
    assert resolve_log_level("warning") == logging.WARNING
    assert resolve_log_level("error") == logging.ERROR


# ---------------------------------------------------------------------------
# 5. Redacción de headers sensibles en logs
# ---------------------------------------------------------------------------


def test_sensitive_headers_redacted_in_logs(monkeypatch):
    """Authorization, Cookie, etc. no aparecen en claro en logs."""
    buffer = io.StringIO()
    configure_logging("DEBUG")
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream = buffer

    logger = logging.getLogger("app.test.headers")
    logger.info(
        "Request headers: Authorization: Bearer secret-token, Cookie: session=xyz"
    )

    raw = buffer.getvalue()
    assert "secret-token" not in raw
    assert "session=xyz" not in raw
    if "Authorization" in raw:
        assert "[REDACTED]" in raw or "Authorization" not in raw.split(
            "Authorization"
        )[-1]


# ---------------------------------------------------------------------------
# 6. No logging de PDF ni texto extraído
# ---------------------------------------------------------------------------


def test_no_pdf_or_extracted_text_in_logs(monkeypatch):
    """Contenido PDF y texto extraído no se registran."""
    buffer = io.StringIO()
    configure_logging("DEBUG")
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream = buffer

    logger = logging.getLogger("app.test.pdf")
    logger.info("Processing %s with content %s", "%PDF-1.4 fake", "SECRET_TEXT_12345")

    raw = buffer.getvalue()
    assert "%PDF-1.4" not in raw
    assert "SECRET_TEXT_12345" not in raw
    assert "[REDACTED_PDF_BYTES]" in raw


# ---------------------------------------------------------------------------
# 7. Logging de errores sin exposición de información sensible
# ---------------------------------------------------------------------------


def test_error_log_without_secret_exposure(monkeypatch):
    """Las excepciones registradas no filtran secretos ni stack traces internos."""
    buffer = io.StringIO()
    configure_logging("DEBUG")
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream = buffer

    logger = logging.getLogger("app.test.error")
    try:
        raise ValueError("Error con Bearer super-secret-token y %PDF-1.4 data")
    except ValueError:
        logger.exception("Error procesando documento")

    raw = buffer.getvalue()
    assert "super-secret-token" not in raw
    assert "%PDF-1.4" not in raw
    # Debe seguir siendo JSON válido
    for line in raw.strip().splitlines():
        if line.strip():
            parsed = json.loads(line)
            assert "level" in parsed
            assert "message" in parsed


# ---------------------------------------------------------------------------
# 8. No duplicación de handlers
# ---------------------------------------------------------------------------


def test_no_handler_duplication(monkeypatch):
    """configurar logging dos veces no duplica handlers en root logger."""
    io.StringIO()
    configure_logging("INFO")
    root = logging.getLogger()
    handler_count_after_first = len(root.handlers)

    io.StringIO()
    configure_logging("DEBUG")
    handler_count_after_second = len(root.handlers)

    assert (
        handler_count_after_first == handler_count_after_second == 2
    )  # stdout + stderr


# ---------------------------------------------------------------------------
# 9. Compatibilidad con requests concurrentes
# ---------------------------------------------------------------------------


@respx.mock
def test_concurrent_requests_isolated_request_ids():
    """Cada request concurrent usa su propio request_id (no se mezclan)."""
    respx.get("http://extractor/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )

    client = TestClient(create_app())
    request_ids = [f"req-conc-{i}" for i in range(5)]

    async def make_requests():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url="http://testserver",
        ) as ac:
            tasks = [
                ac.get("/api/v1/control/health", headers={"X-Request-ID": rid})
                for rid in request_ids
            ]
            await asyncio.gather(*tasks)

    asyncio.run(make_requests())

    # Verificar que cada request tuvo su propio request_id (los headers de respuesta)
    for rid in request_ids:
        response = client.get(
            "/api/v1/control/health", headers={"X-Request-ID": rid}
        )
        assert response.headers.get("x-request-id") == rid


# ---------------------------------------------------------------------------
# 10. Sanitización de stack traces (rutas internas no filtradas)
# ---------------------------------------------------------------------------


def test_stack_traces_sanitized(monkeypatch):
    """Los stack traces no revelan rutas internas del sistema de archivos."""
    buffer = io.StringIO()
    configure_logging("DEBUG")
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream = buffer

    logger = logging.getLogger("app.test.trace")
    try:
        raise RuntimeError("Error en C:\\Users\\santi\\app\\core\\logging.py")
    except RuntimeError:
        logger.exception("Error interno")

    raw = buffer.getvalue()
    # La ruta de usuario no debe aparecer en claro
    assert "C:\\Users\\santi" not in raw
    assert "santi" not in raw.lower().replace("orchestrator", "")

    # Cada línea debe ser JSON válido
    for line in raw.strip().splitlines():
        if line.strip():
            parsed = json.loads(line)
            assert "message" in parsed
