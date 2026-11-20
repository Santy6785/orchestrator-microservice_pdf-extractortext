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
    resultado = await client.extract_document({"filename": "test.pdf"})
    assert route.called
    assert resultado == {"status": "ok"}


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
