"""Capa 2 (Integración con respx): contratos downstream."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.main import create_app
from app.services.validation import compute_sha256_hex

VALID_PDF = b"%PDF-1.4 contrato downstream"
CHECKSUM = compute_sha256_hex(VALID_PDF)
EXTRACTOR_BASE = settings.extractor_service_url
PERSISTENCE_BASE = settings.persistence_service_url


def _fresh_client() -> TestClient:
    return TestClient(create_app())


@respx.mock
def test_contract_downstream_409_duplicate_from_persistence():
    """Contrato 409: persistencia detecta checksum existente -> orquestador 409."""
    respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
        return_value=Response(200, json={"id": "existing-409", "checksum": CHECKSUM})
    )
    extractor_route = respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
        return_value=Response(200, json={"content": "x", "page_count": 1})
    )

    response = _fresh_client().post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 409
    assert response.json()["existing_id"] == "existing-409"
    assert not extractor_route.called


@respx.mock
def test_contract_downstream_404_not_found_on_get_and_delete():
    """Contrato 404: persistencia 404 en GET y DELETE se propaga como 404."""
    doc_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{doc_id}").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )
    respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{doc_id}").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )

    client = _fresh_client()
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404
    assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 404


@respx.mock
def test_contract_downstream_422_validation_error_from_extractor():
    """Contrato 422: error de validación del extractor -> 422."""
    respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
        return_value=Response(404, json={"detail": "not found"})
    )
    respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
        return_value=Response(422, json={"detail": "Unprocessable PDF"})
    )

    response = _fresh_client().post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "extractor_unprocessable"


@respx.mock
@patch("app.clients.base.asyncio.sleep")
def test_contract_downstream_503_returns_502_without_retry(mock_sleep):
    """Contrato 503: un POST al extractor no reintenta por status HTTP."""
    respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
        return_value=Response(404, json={"detail": "not found"})
    )
    extract_route = respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
        return_value=Response(503, json={"detail": "Service Unavailable"})
    )

    response = _fresh_client().post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )

    assert response.status_code == 502
    assert extract_route.call_count == 1
    assert response.json()["code"] == "extractor_error"
    mock_sleep.assert_not_called()

@respx.mock
def test_contract_downstream_timeout_returns_503():
    """Contrato timeout: ReadTimeout en extractor responde 503 (matriz O-16)."""
    respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
        return_value=Response(404, json={"detail": "not found"})
    )
    respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
        side_effect=httpx.ReadTimeout(
            "read timeout",
            request=httpx.Request("POST", f"{EXTRACTOR_BASE}/api/v1/extract"),
        )
    )

    response = _fresh_client().post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "extractor_timeout"
