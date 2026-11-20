"""Tests for issue O-05: Chequeo fail-fast de duplicado en persistencia.

Utiliza respx para interceptar llamadas HTTP a persistencia y extractor,
evitando llamadas de red reales.
"""

import httpx
import respx
from httpx import Response
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_ingestion_service
from app.services.ingestion import IngestionService
from app.services.validation import compute_sha256_hex

VALID_PDF = b"%PDF-1.4 test content for duplicate check"
CHECKSUM = compute_sha256_hex(VALID_PDF)
PERSISTENCE_BASE = "http://persistence:8000"
EXTRACTOR_BASE = "http://extractor"


def _client_with_real_service():
    """Devuelve un TestClient que usa IngestionService real.

    Restaura el dependency_overrides previo al salir para no interferir con
    otros modulos de test (p. ej. test_documents.py usa DummyIngestionService).
    """
    previous_override = app.dependency_overrides.get(get_ingestion_service)
    app.dependency_overrides[get_ingestion_service] = lambda: IngestionService()
    client = TestClient(app)
    try:
        yield client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_ingestion_service, None)
        else:
            app.dependency_overrides[get_ingestion_service] = previous_override


@respx.mock
def test_duplicate_document_returns_409_without_calling_extractor():
    """Caso 1: Persistencia responde 200 (duplicado) -> HTTP 409, sin llamar al extractor."""
    for client in _client_with_real_service():
        checksum_route = respx.get(
            f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}"
        ).mock(
            return_value=Response(
                200, json={"exists": True, "document_id": "doc-123", "checksum": CHECKSUM}
            )
        )
        extractor_route = respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(200, json={"status": "ok"})
        )

        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", VALID_PDF, "application/pdf")},
        )

        assert response.status_code == 409
        body = response.json()
        assert "detail" in body
        assert body["detail"]["existing_id"] == "doc-123"
        assert checksum_route.called
        assert not extractor_route.called


@respx.mock
def test_nonexistent_document_continues_to_extractor():
    """Caso 2: Persistencia responde 404 -> flujo continua, no hay 409."""
    for client in _client_with_real_service():
        checksum_route = respx.get(
            f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}"
        ).mock(
            return_value=Response(404, json={"exists": False, "checksum": CHECKSUM})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(200, json={"status": "ok"})
        )
        respx.post(
            f"{PERSISTENCE_BASE}/api/v1/documents/test.pdf"
        ).mock(return_value=Response(201, json={"id": "doc-456"}))

        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", VALID_PDF, "application/pdf")},
        )

        # No se produce 409: el chequeo de duplicado no bloquea el flujo.
        assert response.status_code != 409
        # El endpoint siempre responde 202 con ProcessingResult.
        assert response.status_code == 202
        body = response.json()
        assert "document_id" in body
        assert "status" in body
        # La consulta by-checksum a persistencia fue realizada.
        assert checksum_route.called


@respx.mock
def test_persistence_5xx_returns_502_without_calling_extractor():
    """Caso 3: Persistencia responde 500 -> HTTP 502, sin llamar al extractor."""
    for client in _client_with_real_service():
        checksum_route = respx.get(
            f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}"
        ).mock(return_value=Response(500, json={"error": "internal error"}))
        extractor_route = respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(200, json={"status": "ok"})
        )

        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", VALID_PDF, "application/pdf")},
        )

        assert response.status_code == 502
        body = response.json()
        assert "detail" in body
        assert checksum_route.called
        assert not extractor_route.called


@respx.mock
def test_persistence_connection_error_returns_502_without_calling_extractor():
    """Caso 4: Error de comunicacion con persistencia -> HTTP 502, sin llamar al extractor."""
    for client in _client_with_real_service():
        checksum_route = respx.get(
            f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}"
        ).mock(side_effect=httpx.ConnectError("Connection failed"))
        extractor_route = respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(200, json={"status": "ok"})
        )

        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", VALID_PDF, "application/pdf")},
        )

        assert response.status_code == 502
        body = response.json()
        assert "detail" in body
        assert checksum_route.called
        assert not extractor_route.called
