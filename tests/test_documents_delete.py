"""Pruebas de integración para DELETE /api/v1/documents/{document_id} (issue O-12).

Utiliza respx para interceptar la solicitud HTTP al microservicio de
persistencia y verificar el comportamiento del endpoint a través de las
capas reales (router -> IngestionService -> PersistenceClient -> httpx).

Cada prueba crea su propia instancia de la app con create_app() para no
heredar el override de dependencia de tests/test_documents.py.
"""

from httpx import Response
import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import settings

PERSISTENCE_BASE = settings.persistence_service_url


def _client():
    """Crea un TestClient sobre una app fresca sin dependency overrides."""
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# CASO 1 — Borrado exitoso: persistencia 204 -> orquestador 204 con body vacío
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_persistence_204_returns_204_empty_body():
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(204)
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert route.called


# ---------------------------------------------------------------------------
# CASO 2 — Documento inexistente: persistencia 404 -> orquestador 404
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_persistence_404_returns_404():
    """Persistencia 404 no debe convertirse en 500 ni 502."""
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(404, json={"detail": "Documento no encontrado"})
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert route.called


# ---------------------------------------------------------------------------
# CASO 3 — Error HTTP de persistencia: 500 -> orquestador 502
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_persistence_500_returns_502():
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(500, json={"detail": "error interno de persistencia"})
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 502
    body = response.json()
    assert "detail" in body
    assert route.called


# ---------------------------------------------------------------------------
# CASO 4 — Error de conexión: ConnectError -> orquestador 502
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_connection_error_returns_502():
    """No deben filtrarse detalles internos de transporte al cliente."""
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        side_effect=httpx.ConnectError("connection failed")
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 502
    body = response.json()
    assert "detail" in body
    assert route.called


# ---------------------------------------------------------------------------
# CASO 5 — Timeout: ReadTimeout -> orquestador 502
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_read_timeout_returns_502():
    document_id = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        side_effect=httpx.ReadTimeout(
            "read timeout",
            request=httpx.Request("DELETE", f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}"),
        )
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 502
    body = response.json()
    assert "detail" in body
    assert route.called


# ---------------------------------------------------------------------------
# CASO 6 — ID inválido: DELETE usa str, no valida UUID, no devuelve 422
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_invalid_id_calls_persistence_without_422():
    """DELETE acepta cualquier string como ID; no hay validación de UUID en esta ruta.
    No devuelve 422; delega a persistencia tal cual se recibe."""
    document_id = "no-es-un-id-valido"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(204)
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert route.called
    assert route.calls[0].request.url.path == f"/api/v1/documents/{document_id}"


# ---------------------------------------------------------------------------
# CASO 7 — Delegación: DELETE sobre URL downstream correcta, ID coincide
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_delegates_delete_with_correct_id_and_no_body():
    document_id = "doc-123"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(204)
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 204
    assert route.called
    assert route.calls[0].request.method == "DELETE"
    assert route.calls[0].request.url.path == f"/api/v1/documents/{document_id}"
    # DELETE no envía body JSON
    assert route.calls[0].request.content == b"" or route.calls[0].request.content is None


# ---------------------------------------------------------------------------
# CASO 8 — Respuesta 204 sin contenido: no hay excepción de parseo JSON
# ---------------------------------------------------------------------------

@respx.mock
def test_delete_document_204_empty_response_no_json_parse_exception():
    """Una respuesta 204 vacía no debe provocar excepción al intentar
    decodificar JSON inexistente."""
    document_id = "doc-123"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(204, content=b"")
    )

    client = _client()
    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert route.called
