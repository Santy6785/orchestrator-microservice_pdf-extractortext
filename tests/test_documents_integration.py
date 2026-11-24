"""Pruebas de integración para GET /api/v1/documents/{document_id} (issue O-11).

Utiliza respx para interceptar la llamada HTTP real al microservicio de
persistencia y verificar el comportamiento del endpoint a través de las
capas reales (router → IngestionService → PersistenceClient → httpx).

Cada prueba crea su propia instancia de la app con create_app() para no
heredar el override de dependencia de tests/test_documents.py.
"""

from fastapi.testclient import TestClient

import respx
from httpx import Response

from app.main import create_app
from app.core.config import settings

PERSISTENCE_BASE = settings.persistence_service_url


def _client():
    """Crea un TestClient sobre una app fresca sin dependency overrides."""
    return TestClient(create_app())


@respx.mock
def test_get_document_persistence_200_returns_200_with_fields():
    """Caso 1: Persistencia 200 con documento completo -> HTTP 200 con los 4 campos."""
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(
            200,
            json={
                "id": document_id,
                "checksum": (
                    "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b"
                ),
                "extracted_text": "Texto completo extraído del documento PDF...",
                "created_at": "2026-10-19T10:30:00",
            },
        )
    )

    client = _client()
    response = client.get(f"/api/v1/documents/{document_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == document_id
    assert data["checksum"] == (
        "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b"
    )
    assert data["extracted_text"] == "Texto completo extraído del documento PDF..."
    assert data["created_at"] == "2026-10-19T10:30:00"
    assert route.called


@respx.mock
def test_get_document_persistence_404_returns_404_with_detail():
    """Caso 2: Persistencia 404 (documento inexistente) -> HTTP 404 con detail."""
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(404, json={"detail": "Documento no encontrado"})
    )

    client = _client()
    response = client.get(f"/api/v1/documents/{document_id}")

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert route.called


@respx.mock
def test_get_document_persistence_connection_error_returns_503_not_404():
    """Caso 4: Error de conexión con persistencia -> HTTP 503, nunca 404."""
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    import httpx

    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        side_effect=httpx.ConnectError("connection failed")
    )

    client = _client()
    response = client.get(f"/api/v1/documents/{document_id}")

    assert response.status_code == 503
    body = response.json()
    assert "detail" in body
    assert body["code"] == "persistence_connection_error"
    assert route.called


@respx.mock
def test_get_document_persistence_incomplete_response_returns_error():
    """Caso 5: Persistencia 200 con campos incompletos -> error de serialización."""
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(200, json={"id": document_id})
    )

    # raise_server_exceptions=False permite capturar la respuesta de error.
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.get(f"/api/v1/documents/{document_id}")

    # DocumentDetailResponse requiere los 4 campos; la falta provoca error 500.
    assert response.status_code == 500
    assert route.called
