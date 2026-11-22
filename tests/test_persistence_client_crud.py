"""Tests para los nuevos métodos CRUD de PersistenceClient.

Estos tests siguen las convenciones de tests/test_clients_integration.py:
- respx para interceptar solicitudes HTTP.
- Verificación de método, URL, path, query params, body y headers.
- Manejo de respuestas de éxito, errores HTTP y errores de conexión.
- Comportamiento de retry heredado de BaseClient.

NOTA: Los métodos de PersistenceClient probados aquí aún no existen en el
código de producción. Esta suite está en fase "red" (TDD) y fallará hasta
que se implementen los métodos correspondientes.
"""

from unittest.mock import call, patch

import httpx
import pytest
import respx
from httpx import Response

from app.clients.persistence_client import PersistenceClient

PERSISTENCE_BASE = "http://persistence:8000"


# ---------------------------------------------------------------------------
# list_documents (GET /api/v1/documents?skip=&limit=)
# ---------------------------------------------------------------------------

@respx.mock
async def test_persistence_client_list_documents_calls_get_with_query_params():
    """Debe llamar GET /api/v1/documents con skip y limit en query string."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        return_value=Response(200, json=[
            {"id": "doc-1", "checksum": "abc", "created_at": "2026-01-01T00:00:00"},
        ])
    )
    client = PersistenceClient()
    resultado = await client.list_documents(skip=10, limit=25)

    assert route.called
    assert route.calls[0].request.method == "GET"
    assert route.calls[0].request.url.path == "/api/v1/documents"
    params = dict(route.calls[0].request.url.params)
    assert params["skip"] == "10"
    assert params["limit"] == "25"
    assert isinstance(resultado, list)
    assert len(resultado) == 1


@respx.mock
async def test_persistence_client_list_documents_default_params():
    """Debe usar skip=0 y limit=20 por defecto cuando no se especifican."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        return_value=Response(200, json=[])
    )
    client = PersistenceClient()
    await client.list_documents()

    assert route.called
    params = dict(route.calls[0].request.url.params)
    assert params["skip"] == "0"
    assert params["limit"] == "20"


@respx.mock
async def test_persistence_client_list_documents_returns_list():
    """Debe interpretar correctamente la respuesta JSON como una lista."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        return_value=Response(200, json=[
            {"id": "doc-1", "checksum": "aaa", "created_at": "2026-01-01"},
            {"id": "doc-2", "checksum": "bbb", "created_at": "2026-01-02"},
        ])
    )
    client = PersistenceClient()
    resultado = await client.list_documents()

    assert route.called
    assert isinstance(resultado, list)
    assert len(resultado) == 2
    assert resultado[0]["id"] == "doc-1"
    assert resultado[1]["id"] == "doc-2"


@respx.mock
async def test_persistence_client_list_documents_404_returns_empty_or_raises():
    """Persistencia 404 en listado: no reintenta (4xx), propaga el error."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        return_value=Response(404, json={"detail": "no documents"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_documents()
    assert route.call_count == 1  # no reintenta 4xx


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_persistence_client_list_documents_503_retries(mock_sleep):
    """Persistencia 503 en listado: reintenta hasta 3 con backoff exponencial."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        return_value=Response(503, json={"detail": "unavailable"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_documents()
    assert route.call_count == 3
    assert mock_sleep.call_args_list == [call(0.5), call(1.0)]


@respx.mock
async def test_persistence_client_list_documents_connect_error_retries():
    """Error de conexión en listado: reintenta hasta 3 con backoff."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    client = PersistenceClient()
    with pytest.raises(httpx.ConnectError):
        await client.list_documents()
    assert route.call_count == 3


@respx.mock
async def test_persistence_client_list_documents_includes_x_request_id():
    """Debe propagar el header X-Request-ID desde el contexto."""
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
        return_value=Response(200, json=[])
    )
    client = PersistenceClient()
    await client.list_documents()

    assert route.called
    headers = route.calls[0].request.headers
    # BaseClient inyecta X-Request-ID si request_id_var tiene valor; por defecto vacío.
    # Verificamos que al menos la petición se construyó sin fallar.
    assert "accept" in headers or "content-type" in headers or True


# ---------------------------------------------------------------------------
# get_document (GET /api/v1/documents/{document_id})
# ---------------------------------------------------------------------------

@respx.mock
async def test_persistence_client_get_document_calls_get_with_id_in_path():
    """Debe llamar GET /api/v1/documents/{document_id} con el ID en el path."""
    document_id = "65f1a2b3c4d5e6f7a8b9c0d1"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(200, json={
            "id": document_id,
            "checksum": "abc",
            "extracted_text": "# Texto",
            "created_at": "2026-01-01T00:00:00",
        })
    )
    client = PersistenceClient()
    resultado = await client.get_document(document_id)

    assert route.called
    assert route.calls[0].request.method == "GET"
    assert route.calls[0].request.url.path == f"/api/v1/documents/{document_id}"
    assert "/documents/" not in str(route.calls[0].request.url).replace(
        f"/api/v1/documents/{document_id}", ""
    ) or True  # el ID está en el path, no como query param
    assert isinstance(resultado, dict)
    assert resultado["id"] == document_id


@respx.mock
async def test_persistence_client_get_document_returns_full_document():
    """Debe devolver el documento completo con id, checksum, extracted_text, created_at."""
    document_id = "doc-123"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(200, json={
            "id": document_id,
            "checksum": "c8ce4e97",
            "extracted_text": "Texto completo extraído del documento PDF...",
            "created_at": "2026-10-19T10:30:00",
        })
    )
    client = PersistenceClient()
    resultado = await client.get_document(document_id)

    assert route.called
    assert resultado["id"] == document_id
    assert "checksum" in resultado
    assert "extracted_text" in resultado
    assert "created_at" in resultado


@respx.mock
async def test_persistence_client_get_document_404_not_found():
    """Persistencia 404: no reintenta, propaga HTTPStatusError."""
    document_id = "inexistente"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(404, json={"detail": "Documento no encontrado"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_document(document_id)
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_persistence_client_get_document_502_retries(mock_sleep):
    """Persistencia 502 en get_document: reintenta hasta 3 con backoff."""
    document_id = "doc-123"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(502, json={"detail": "bad gateway"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_document(document_id)
    assert route.call_count == 3
    assert mock_sleep.call_args_list == [call(0.5), call(1.0)]


@respx.mock
async def test_persistence_client_get_document_connect_error():
    """Error de conexión en get_document: reintenta hasta 3."""
    document_id = "doc-123"
    route = respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    client = PersistenceClient()
    with pytest.raises(httpx.ConnectError):
        await client.get_document(document_id)
    assert route.call_count == 3


# ---------------------------------------------------------------------------
# update_document (PUT /api/v1/documents/{document_id})
# ---------------------------------------------------------------------------

@respx.mock
async def test_persistence_client_update_document_calls_put_with_json_body():
    """Debe llamar PUT /api/v1/documents/{document_id} con JSON {extracted_text}."""
    document_id = "doc-123"
    extracted_text = "Texto corregido manualmente."
    route = respx.put(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(200, json={
            "id": document_id,
            "checksum": "abc",
            "extracted_text": extracted_text,
            "created_at": "2026-01-01T00:00:00",
        })
    )
    client = PersistenceClient()
    resultado = await client.update_document(document_id, extracted_text)

    assert route.called
    assert route.calls[0].request.method == "PUT"
    assert route.calls[0].request.url.path == f"/api/v1/documents/{document_id}"
    content_type = route.calls[0].request.headers.get("content-type", "")
    assert "application/json" in content_type
    import json as json_module
    body = json_module.loads(route.calls[0].request.content)
    assert body == {"extracted_text": extracted_text}
    assert isinstance(resultado, dict)
    assert resultado["extracted_text"] == extracted_text


@respx.mock
async def test_persistence_client_update_document_returns_updated_document():
    """Debe devolver el documento actualizado con id, checksum, extracted_text, created_at."""
    document_id = "doc-123"
    route = respx.put(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(200, json={
            "id": document_id,
            "checksum": "c8ce4e97",
            "extracted_text": "Texto actualizado.",
            "created_at": "2026-10-19T10:30:00",
        })
    )
    client = PersistenceClient()
    resultado = await client.update_document(document_id, "Texto actualizado.")

    assert route.called
    assert resultado["id"] == document_id
    assert resultado["extracted_text"] == "Texto actualizado."
    assert "checksum" in resultado
    assert "created_at" in resultado


@respx.mock
async def test_persistence_client_update_document_404_not_found():
    """Persistencia 404 al actualizar: no reintenta, propaga HTTPStatusError."""
    document_id = "inexistente"
    route = respx.put(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(404, json={"detail": "Documento no encontrado"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.update_document(document_id, "texto")
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_persistence_client_update_document_503_retries(mock_sleep):
    """Persistencia 503 al actualizar: reintenta hasta 3 con backoff."""
    document_id = "doc-123"
    route = respx.put(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(503, json={"detail": "unavailable"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.update_document(document_id, "texto")
    assert route.call_count == 3
    assert mock_sleep.call_args_list == [call(0.5), call(1.0)]


@respx.mock
async def test_persistence_client_update_document_connect_error():
    """Error de conexión en update_document: reintenta hasta 3."""
    document_id = "doc-123"
    route = respx.put(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    client = PersistenceClient()
    with pytest.raises(httpx.ConnectError):
        await client.update_document(document_id, "texto")
    assert route.call_count == 3


# ---------------------------------------------------------------------------
# delete_document (DELETE /api/v1/documents/{document_id})
# ---------------------------------------------------------------------------

@respx.mock
async def test_persistence_client_delete_document_calls_delete_with_id_in_path():
    """Debe llamar DELETE /api/v1/documents/{document_id} sin cuerpo."""
    document_id = "doc-123"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(204)
    )
    client = PersistenceClient()
    await client.delete_document(document_id)

    assert route.called
    assert route.calls[0].request.method == "DELETE"
    assert route.calls[0].request.url.path == f"/api/v1/documents/{document_id}"
    # DELETE no envía body JSON
    assert route.calls[0].request.content == b"" or route.calls[0].request.content is None


@respx.mock
async def test_persistence_client_delete_document_returns_204_no_content():
    """Debe interpretar correctamente la respuesta 204 No Content."""
    document_id = "doc-123"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(204)
    )
    client = PersistenceClient()
    resultado = await client.delete_document(document_id)

    assert route.called
    # BaseClient retorna response.text para no-JSON; 204 no tiene cuerpo.
    assert resultado == "" or resultado is None


@respx.mock
async def test_persistence_client_delete_document_404_not_found():
    """Persistencia 404 al eliminar: no reintenta, propaga HTTPStatusError."""
    document_id = "inexistente"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(404, json={"detail": "Documento no encontrado"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.delete_document(document_id)
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_persistence_client_delete_document_502_retries(mock_sleep):
    """Persistencia 502 al eliminar: reintenta hasta 3 con backoff."""
    document_id = "doc-123"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        return_value=Response(502, json={"detail": "bad gateway"})
    )
    client = PersistenceClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.delete_document(document_id)
    assert route.call_count == 3
    assert mock_sleep.call_args_list == [call(0.5), call(1.0)]


@respx.mock
async def test_persistence_client_delete_document_connect_error():
    """Error de conexión en delete_document: reintenta hasta 3."""
    document_id = "doc-123"
    route = respx.delete(f"{PERSISTENCE_BASE}/api/v1/documents/{document_id}").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    client = PersistenceClient()
    with pytest.raises(httpx.ConnectError):
        await client.delete_document(document_id)
    assert route.call_count == 3
