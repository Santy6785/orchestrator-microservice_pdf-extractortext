
import json
from unittest.mock import call, patch

import httpx
import pytest
import respx
from httpx import Response

from app.clients.base import BACKOFF, MAX_ATTEMPTS, BaseClient
from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient


@respx.mock
async def test_extractor_client_llama_url_configurada():
    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    client = ExtractorClient()
    resultado = await client.extract_document("test.pdf", b"%PDF-1.4 test")
    assert route.called
    assert resultado == {"status": "ok"}


@respx.mock
async def test_extractor_client_envia_archivo_multipart_correcto():
    """Verifica envío multipart con campo file, nombre, MIME y bytes exactos."""
    pdf_bytes = b"%PDF-1.4 contenido de prueba del PDF"
    filename = "documento.pdf"

    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(200, json={"content": "# Texto", "page_count": 1})
    )

    client = ExtractorClient()
    resultado = await client.extract_document(filename=filename, pdf_bytes=pdf_bytes)

    assert route.called
    assert resultado == {"content": "# Texto", "page_count": 1}

    request = route.calls[0].request

    content_type = request.headers.get("content-type", "")
    assert "multipart/form-data" in content_type
    assert "application/json" not in content_type

    body = request.content
    assert b'name="file"' in body
    assert f'filename="{filename}"'.encode() in body
    assert b"application/pdf" in body
    assert pdf_bytes in body


@respx.mock
async def test_extractor_client_respuesta_exitosa():
    """Verifica devolución correcta de content y page_count (HTTP 200)."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(
            200, json={"content": "# Documento de prueba", "page_count": 3}
        )
    )

    client = ExtractorClient()
    resultado = await client.extract_document("test.pdf", b"%PDF-1.4 test")

    assert route.called
    assert isinstance(resultado, dict)
    assert resultado["content"] == "# Documento de prueba"
    assert resultado["page_count"] == 3


@respx.mock
async def test_extractor_client_timeout_30_segundos():
    """Verifica timeout de 30s en ExtractorClient, sin afectar a Persistence."""
    client = ExtractorClient()
    assert client.timeout == 30.0

    persistence_client = PersistenceClient()
    assert persistence_client.timeout == 5.0


@respx.mock
async def test_extractor_client_no_envia_json_cuerpo():
    """Verifica que la petición multipart no depende de un body JSON."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(200, json={"content": "# Texto", "page_count": 1})
    )

    client = ExtractorClient()
    await client.extract_document("test.pdf", b"%PDF-1.4 test")

    assert route.called
    request = route.calls[0].request

    content_type = request.headers.get("content-type", "")
    assert "multipart/form-data" in content_type
    assert "application/json" not in content_type


@respx.mock
async def test_persistence_client_llama_url_configurada():
    route = respx.post("http://persistence:8000/api/v1/documents").mock(
        return_value=Response(201, json={"id": "doc-123"})
    )
    client = PersistenceClient()
    resultado = await client.register_document({"checksum_sha256": "x"})
    assert route.called
    assert resultado == {"id": "doc-123"}


@respx.mock
async def test_persistence_client_register_document():
    route = respx.post("http://persistence:8000/api/v1/documents").mock(
        return_value=Response(
            201,
            json={
                "id": "65f1a2b3c4d5e6f7a8b9c0d1",
                "checksum_sha256": "a" * 64,
                "filename": "documento.pdf",
                "extracted_text": "# Documento de prueba",
                "page_count": 3,
                "file_size_bytes": 1024,
                "metadata": {"source": "test"},
                "created_at": "2026-10-19T10:30:00",
                "updated_at": "2026-10-19T10:30:00",
            },
        )
    )
    client = PersistenceClient()
    payload = {
        "checksum_sha256": "a" * 64,
        "filename": "documento.pdf",
        "extracted_text": "# Documento de prueba",
        "page_count": 3,
        "file_size_bytes": 1024,
        "metadata": {"source": "test"},
    }
    resultado = await client.register_document(payload)

    assert route.called
    assert route.calls[0].request.method == "POST"
    assert route.calls[0].request.url.path == "/api/v1/documents"
    assert "/documents/" not in str(route.calls[0].request.url)

    body = json.loads(route.calls[0].request.content)
    assert body == payload
    assert set(body.keys()) == {
        "checksum_sha256",
        "filename",
        "extracted_text",
        "page_count",
        "file_size_bytes",
        "metadata",
    }

    assert isinstance(resultado, dict)
    assert resultado["id"] == "65f1a2b3c4d5e6f7a8b9c0d1"
    assert resultado["checksum_sha256"] == "a" * 64


# --- Tests de política de reintentos de BaseClient ---

NON_RETRYABLE_STATUS_CODES = (400, 404, 422, 429, 500)
RETRYABLE_STATUS_CODES = (502, 503, 504)


@respx.mock
@pytest.mark.parametrize("status_code", NON_RETRYABLE_STATUS_CODES)
async def test_non_retryable_status_single_attempt(status_code):
    """Códigos 4xx y 500 se intentan una sola vez."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(status_code, json={"detail": "error"})
    )
    client = ExtractorClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.post("/api/v1/extract", json={"foo": "bar"})
    assert route.call_count == 1


@respx.mock
@patch("app.clients.base.asyncio.sleep")
@pytest.mark.parametrize("status_code", RETRYABLE_STATUS_CODES)
async def test_post_never_retries_on_status(mock_sleep, status_code):
    """POST nunca reintenta por código HTTP, incluidos 502, 503 y 504."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(status_code, json={"detail": "error"})
    )
    client = ExtractorClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.post("/api/v1/extract", json={"foo": "bar"})
    assert route.call_count == 1
    mock_sleep.assert_not_called()


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_connect_error_retries(mock_sleep):
    """ConnectError se reintenta hasta agotar MAX_ATTEMPTS con BACKOFF ordenado."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    client = ExtractorClient()
    with pytest.raises(httpx.ConnectError):
        await client.post("/api/v1/extract", json={"foo": "bar"})
    assert route.call_count == MAX_ATTEMPTS
    assert mock_sleep.call_args_list == [call(0.2), call(0.5)]


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_connect_timeout_retries(mock_sleep):
    """ConnectTimeout se reintenta hasta agotar MAX_ATTEMPTS con BACKOFF ordenado."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        side_effect=httpx.ConnectTimeout("connection timeout")
    )
    client = ExtractorClient()
    with pytest.raises(httpx.ConnectTimeout):
        await client.post("/api/v1/extract", json={"foo": "bar"})
    assert route.call_count == MAX_ATTEMPTS
    assert mock_sleep.call_args_list == [call(0.2), call(0.5)]


def test_clientes_usan_timeout_de_settings(monkeypatch):
    """Los clientes toman su timeout de los settings, sin valores fijos."""
    monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
    monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
    monkeypatch.setenv("EXTRACTOR_TIMEOUT_SECONDS", "45.0")
    monkeypatch.setenv("PERSISTENCE_TIMEOUT_SECONDS", "7.0")

    from app.core.config import Settings

    settings = Settings()
    extractor = ExtractorClient(timeout=settings.extractor_timeout_seconds)
    persistence = PersistenceClient(timeout=settings.persistence_timeout_seconds)

    assert extractor.timeout == 45.0
    assert persistence.timeout == 7.0


# --- Tests de manejo de respuestas HTTP vacías en BaseClient ---


@respx.mock
async def test_base_client_request_204_json_content_type_empty_body():
    """HTTP 204 con Content-Type JSON y body vacío no provoca JSONDecodeError."""
    client = BaseClient(service_url="http://test")
    route = respx.get("http://test/api/v1/resource").mock(
        return_value=Response(204, headers={"content-type": "application/json"})
    )
    resultado = await client._request("GET", "/api/v1/resource")
    assert route.called
    assert resultado == ""


@respx.mock
async def test_base_client_request_200_json_content_type_empty_body():
    """HTTP 200 con Content-Type JSON y body vacío no provoca JSONDecodeError."""
    client = BaseClient(service_url="http://test")
    route = respx.post("http://test/api/v1/resource").mock(
        return_value=Response(
            200, content=b"", headers={"content-type": "application/json"}
        )
    )
    resultado = await client._request("POST", "/api/v1/resource", json={"foo": "bar"})
    assert route.called
    assert resultado == ""


@respx.mock
async def test_base_client_request_200_valid_json_still_deserializes():
    """HTTP 200 con JSON válido sigue deserializándose normalmente."""
    client = BaseClient(service_url="http://test")
    route = respx.post("http://test/api/v1/resource").mock(
        return_value=Response(200, json={"id": "doc-1", "status": "ok"})
    )
    resultado = await client._request("POST", "/api/v1/resource", json={"foo": "bar"})
    assert route.called
    assert resultado == {"id": "doc-1", "status": "ok"}


@respx.mock
async def test_base_client_request_200_plain_text_returns_text():
    """HTTP 200 con texto plano se devuelve como texto."""
    client = BaseClient(service_url="http://test")
    route = respx.get("http://test/api/v1/resource").mock(
        return_value=Response(
            200, text="texto plano", headers={"content-type": "text/plain"}
        )
    )
    resultado = await client._request("GET", "/api/v1/resource")
    assert route.called
    assert resultado == "texto plano"


@respx.mock
async def test_base_client_request_204_no_content_type_returns_empty_text():
    """HTTP 204 sin Content-Type se devuelve como texto vacío."""
    client = BaseClient(service_url="http://test")
    route = respx.delete("http://test/api/v1/resource").mock(
        return_value=Response(204)
    )
    resultado = await client._request("DELETE", "/api/v1/resource")
    assert route.called
    assert resultado == ""


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_base_client_empty_json_body_not_retried(mock_sleep):
    """Body JSON vacío no se reintenta: exactamente un intento."""
    client = BaseClient(service_url="http://test")
    route = respx.post("http://test/api/v1/resource").mock(
        return_value=Response(
            200, content=b"", headers={"content-type": "application/json"}
        )
    )
    resultado = await client._request("POST", "/api/v1/resource", json={"foo": "bar"})
    assert route.called
    assert resultado == ""
    assert route.call_count == 1
    mock_sleep.assert_not_called()


@respx.mock
async def test_persistence_client_delete_document_204_json_content_type():
    """PersistenceClient.delete_document con 204 y Content-Type JSON devuelve texto vacío."""
    document_id = "doc-123"
    route = respx.delete(
        f"http://persistence:8000/api/v1/documents/{document_id}"
    ).mock(
        return_value=Response(204, headers={"content-type": "application/json"})
    )
    client = PersistenceClient()
    resultado = await client.delete_document(document_id)
    assert route.called
    assert resultado == ""


@respx.mock
@patch("app.clients.base.asyncio.sleep")
async def test_persistence_get_readtimeout_reintenta_sin_dormir(mock_sleep):
    """GET a persistencia con ReadTimeout se reintenta (O-14) sin dormir de verdad."""
    client = PersistenceClient()
    route = respx.get(
        "http://persistence:8000/api/v1/documents/by-checksum/abc"
    ).mock(
        side_effect=httpx.ReadTimeout("read timeout")
    )
    with pytest.raises(httpx.ReadTimeout):
        await client.get("/api/v1/documents/by-checksum/abc")

    assert route.call_count == MAX_ATTEMPTS
    assert mock_sleep.call_args_list == [
        call(BACKOFF[0]),
        call(BACKOFF[1]),
    ]
