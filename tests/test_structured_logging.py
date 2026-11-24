import io
import json
import logging
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.logging import JsonLogFormatter, configure_logging, resolve_log_level
from app.core.middleware import request_id_var
from app.dependencies import get_ingestion_service
from app.main import create_app
from app.services.ingestion import IngestionService


def test_json_formatter_outputs_required_fields():
    formatter = JsonLogFormatter()
    token = request_id_var.set("req-abc-123")
    try:
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Document %s processed",
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
        assert parsed["level"] == "INFO"
        assert parsed["service"] == "orchestrator"
        assert parsed["request_id"] == "req-abc-123"
        assert parsed["message"] == "Document doc-1 processed"
        assert "T" in parsed["timestamp"]
    finally:
        request_id_var.reset(token)


def test_resolve_log_level_supports_aliases(monkeypatch):
    assert resolve_log_level("debug") == logging.DEBUG
    assert resolve_log_level("info") == logging.INFO
    assert resolve_log_level("warn") == logging.WARNING
    assert resolve_log_level("warning") == logging.WARNING
    assert resolve_log_level("error") == logging.ERROR

    monkeypatch.setenv("LOG_LEVEL", "warn")
    assert resolve_log_level() == logging.WARNING


def test_configure_logging_writes_json_to_stdout(monkeypatch):
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)
    configure_logging("INFO")

    token = request_id_var.set("req-stdout-999")
    try:
        logging.getLogger("app.test.stdout").info("Hello structured log")
    finally:
        request_id_var.reset(token)

    lines = [line for line in buffer.getvalue().strip().splitlines() if line]
    assert len(lines) >= 1
    entry = json.loads(lines[-1])
    assert entry["level"] == "INFO"
    assert entry["service"] == "orchestrator"
    assert entry["request_id"] == "req-stdout-999"
    assert entry["message"] == "Hello structured log"
    assert "timestamp" in entry


def test_sensitive_data_is_never_logged_during_upload(monkeypatch):
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    app = create_app()
    # Rebind stdout stream after create_app() calls configure_logging()
    monkeypatch.setattr("sys.stdout", buffer)
    configure_logging("DEBUG")

    secret_extracted_text = "CONFIDENTIAL_SALARY_REPORT_987654321"
    secret_auth_token = "Bearer super-secret-jwt-token-xyz"
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"

    mock_extractor = AsyncMock()
    mock_extractor.extract_document.return_value = {
        "content": secret_extracted_text,
        "page_count": 2,
    }

    mock_persistence = AsyncMock()
    import httpx

    req = httpx.Request("GET", "http://persistence:8000/api/v1/documents/by-checksum/x")
    resp = httpx.Response(404, request=req)
    mock_persistence.check_duplicate_by_checksum.side_effect = httpx.HTTPStatusError(
        "Not found", request=req, response=resp
    )
    mock_persistence.register_document.return_value = {
        "id": "doc-sensitive-1",
        "created_at": "2026-11-24T12:00:00Z",
    }

    service = IngestionService(
        extractor_client=mock_extractor,
        persistence_client=mock_persistence,
    )
    app.dependency_overrides[get_ingestion_service] = lambda: service

    client = TestClient(app)
    response = client.post(
        "/api/v1/documents/upload",
        headers={
            "X-Request-ID": "req-sensitive-check-01",
            "Authorization": secret_auth_token,
        },
        files={"file": ("secret.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200

    # Also verify direct redaction if sensitive headers or PDF bytes reach logger
    logging.getLogger("app.test.redaction").info(
        "Headers: Authorization: %s raw=%s", secret_auth_token, "%PDF-1.4 binary"
    )

    raw_logs = buffer.getvalue()
    assert raw_logs.strip() != ""
    assert secret_extracted_text not in raw_logs
    assert "super-secret-jwt-token-xyz" not in raw_logs
    assert "%PDF-1.4" not in raw_logs

    # Every emitted line must be valid JSON with required keys
    for line in raw_logs.strip().splitlines():
        parsed = json.loads(line)
        assert {"timestamp", "level", "service", "request_id", "message"} <= set(
            parsed.keys()
        )