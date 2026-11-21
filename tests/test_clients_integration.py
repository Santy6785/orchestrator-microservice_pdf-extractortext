import json
from unittest.mock import call, patch

import httpx
import pytest
import respx
from httpx import Response

from app.clients.base import MAX_ATTEMPTS
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
    """TEST 1: Verifica envío multipart con campo file, nombre, MIME y bytes exactos."""
    pdf_bytes = b"%PDF-1.4 contenido de prueba del PDF"
    filename = "documento.pdf"

    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(200, json={"content": "# Texto", "page_count": 1})
    )

    client = ExtractorClient()
    resultado = await client.extract_document(filename=filename, pdf_bytes=pdf_bytes)

    assert route.called
    assert resultado == {"content": "# Texto", "page_count": 1}

    call = route.calls[0]
    request = call.request

    # Content-Type multipart/form-data (no application/json)
    content_type = request.headers.get("content-type", "")
    assert "multipart/form-data" in content_type
    assert "application/json" not in content_type

    # Cuerpo multipart contiene el campo, nombre, MIME y los bytes originales
    body = request.content
    assert b'name="file"' in body
    assert f'filename="{filename}"'.encode() in body
    assert b"application/pdf" in body
    assert pdf_bytes in body


@respx.mock
async def test_extractor_client_respuesta_exitosa():
    """TEST 2: Verifica devolución correcta de content y page_count (HTTP 200)."""
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
    """TEST 3: Verifica timeout de 30s solo en ExtractorClient, sin afectar a otros."""
    client = ExtractorClient()
    assert client.timeout == 30.0

    # BaseClient default y PersistenceClient no se ven afectados
    persistence_client = PersistenceClient()
    assert persistence_client.timeout == 5.0


@respx.mock
async def test_extractor_client_no_envia_json_cuerpo():
    """TEST 4: Verifica que la petición no depende de un body JSON con filename/metadata."""
    route = respx.post("http://extractor/api/v1/extract").mock(
        return_value=Response(200, json={"content": "# Texto", "page_count": 1})
    )

    client = ExtractorClient()
    await client.extract_document("test.pdf", b"%PDF-1.4 test")

    assert route.called
    call = route.calls[0]
    request = call.request

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

    # 1. La petición fue ejecutada.
    assert route.called
    # 2. El método HTTP es POST.
    assert route.calls[0].request.method == "POST"
    # 3. La URL es exactamente /api/v1/documents.
    assert route.calls[0].request.url.path == "/api/v1/documents"
    # 4. La URL no contiene ningún ID.
    assert "/documents/" not in str(route.calls[0].request.url)
    # 5. El cuerpo JSON coincide exactamente con el payload esperado.
    body = json.loads(route.calls[0].request.content)
    assert body == payload
    # 6. No se envían campos adicionales.
    assert set(body.keys()) == {
        "checksum_sha256",
        "filename",
        "extracted_text",
        "page_count",
        "file_size_bytes",
        "metadata",
    }
    # 7. El cliente devuelve correctamente el JSON de respuesta.
    assert isinstance(resultado, dict)
    # 8. El ID devuelto coincide con el generado por persistencia.
    assert resultado["id"] == "65f1a2b3c4d5e6f7a8b9c0d1"
    assert resultado["checksum_sha256"] == "a" * 64


@respx.mock
async def test_persistence_client_valida_documento():
    route = respx.get("http://persistence:8000/api/v1/documents/abc/validate").mock(
        return_value=Response(200, json={"valid": True})
    )
    client = PersistenceClient()
    assert await client.validate_document("abc") is True
    assert route.called


# --- Tests de política de reintentos de BaseClient ---

NON_RETRYABLE_STATUS_CODES = (400, 404, 422, 429, 500)
RETRYABLE_STATUS_CODES = (502, 503, 504)


@respx.mock
@pytest.mark.parametrize("status_code", NON_RETRYABLE_STATUS_CODES)
async def test_non_retryable_status_single_attempt(status_code):
    """Códigos 4xx y 500 se intentan una sola vez (no se reintentan)."""
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
    """POST nunca reintenta por código de estado (502/503/504 incluido): 1 llamada."""
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
    # BACKOFF = (0.2, 0.5, 1.0): espera antes del reintento k es BACKOFF[k-1].
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
    # BACKOFF = (0.2, 0.5, 1.0): espera antes del reintento k es BACKOFF[k-1].
    assert mock_sleep.call_args_list == [call(0.2), call(0.5)]
