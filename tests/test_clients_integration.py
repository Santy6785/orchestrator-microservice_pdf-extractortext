import respx
from httpx import Response

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
    route = respx.post("http://persistence:8000/api/v1/documents/abc").mock(
        return_value=Response(201, json={"id": "abc"})
    )
    client = PersistenceClient()
    resultado = await client.register_document("abc", {"checksum": "x"})
    assert route.called
    assert resultado == {"id": "abc"}


@respx.mock
async def test_persistence_client_valida_documento():
    route = respx.get("http://persistence:8000/api/v1/documents/abc/validate").mock(
        return_value=Response(200, json={"valid": True})
    )
    client = PersistenceClient()
    assert await client.validate_document("abc") is True
    assert route.called
