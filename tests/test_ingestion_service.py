"""Tests for IngestionService integration with ExtractorClient (issue O-06).

Utiliza dobles de prueba simples para evitar llamadas reales a Persistencia
y Extractor, verificando el flujo de extracción y mapeo de respuesta.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.services.ingestion import IngestionService

VALID_PDF = b"%PDF-1.4 contenido de prueba del PDF"
FILENAME = "documento.pdf"
CHECKSUM = "a" * 64


class MockExtractorClient:
    """Doble de prueba que captura los argumentos de extract_document."""

    def __init__(
        self,
        return_value: dict[str, Any] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.return_value = return_value or {"content": "# Documento", "page_count": 5}
        self.exc = exc

    async def extract_document(self, filename: str, pdf_bytes: bytes) -> dict[str, Any]:
        self.calls.append((filename, pdf_bytes))
        if self.exc is not None:
            raise self.exc
        return self.return_value


class MockPersistenceClient:
    """Doble de prueba que captura llamadas a persistencia sin red real."""

    def __init__(self) -> None:
        self.registered_payload: dict[str, Any] | None = None
        self.registered_document_id: str | None = None

    async def check_duplicate_by_checksum(self, checksum: str) -> Any:
        # Simula HTTP 404: no hay duplicado, el flujo continúa.
        request = httpx.Request("GET", "http://persistence/check")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    async def register_document(self, document_id: str, payload: dict[str, Any]) -> Any:
        self.registered_document_id = document_id
        self.registered_payload = payload
        return {"id": document_id}


class DuplicatePersistence(MockPersistenceClient):
    """Persistencia que simula documento duplicado (HTTP 200, O-05)."""

    async def check_duplicate_by_checksum(self, checksum: str) -> Any:
        return {"document_id": "doc-existente", "checksum": checksum}


def _make_service(
    extractor_return: dict[str, Any] | None = None,
    extractor_exc: Exception | None = None,
) -> tuple[IngestionService, MockExtractorClient, MockPersistenceClient]:
    extractor = MockExtractorClient(return_value=extractor_return, exc=extractor_exc)
    persistence = MockPersistenceClient()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )
    return service, extractor, persistence


def _base_payload() -> dict[str, Any]:
    return {"filename": FILENAME, "content": VALID_PDF, "checksum": CHECKSUM}


@pytest.mark.asyncio
async def test_ingestion_extrae_filename_y_bytes_desde_payload():
    """El servicio extrae filename y content del payload y los pasa al extractor."""
    service, extractor, _persistence = _make_service()
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.status == "queued"
    assert len(extractor.calls) == 1
    called_filename, called_bytes = extractor.calls[0]
    assert called_filename == FILENAME
    assert called_bytes == VALID_PDF


@pytest.mark.asyncio
async def test_ingestion_interpreta_respuesta_exitosa():
    """Respeto de content y page_count del extractor."""
    service, _extractor, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["extracted_text"] == "# Documento"
    assert persistence.registered_payload["page_count"] == 5


@pytest.mark.asyncio
async def test_ingestion_conserva_bytes_originales_en_payload():
    """payload['content'] conserva los bytes del PDF; no se sobrescribe."""
    service, _, _ = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert payload["content"] == VALID_PDF


@pytest.mark.asyncio
async def test_ingestion_guarda_extraido_en_nuevas_claves():
    """extracted_text y page_count se agregan al payload sin perder contenido previo."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert payload["filename"] == FILENAME
    assert payload["checksum"] == CHECKSUM
    assert payload["content"] == VALID_PDF
    assert payload["extracted_text"] == "# Documento"
    assert payload["page_count"] == 5
    assert persistence.registered_payload is payload


@pytest.mark.asyncio
async def test_ingestion_extraer_sin_campos_obligatorios_devuelve_failed():
    """Respuesta sin 'content' o 'page_count' -> failed, sin continuar."""
    service, _extractor, persistence = _make_service(
        extractor_return={"content": "# Documento"}  # falta page_count
    )
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.status == "failed"
    assert persistence.registered_payload is None  # no se registró en persistencia


@pytest.mark.asyncio
async def test_ingestion_extraer_con_tipos_invalidos_devuelve_failed():
    """content no string o page_count no int -> failed."""
    service, _, persistence = _make_service(
        extractor_return={"content": 123, "page_count": "cinco"}  # type: ignore[dict-item]
    )
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.status == "failed"
    assert persistence.registered_payload is None


@pytest.mark.asyncio
async def test_ingestion_error_del_extractor_mantiene_comportamiento_de_error():
    """Excepción en el extractor -> failed con detalle del error."""
    service, _, persistence = _make_service(
        extractor_exc=RuntimeError("extractor caído")
    )
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.status == "failed"
    assert "extractor caído" in result.detail
    assert persistence.registered_payload is None


@pytest.mark.asyncio
async def test_ingestion_no_llama_al_extractor_cuando_es_duplicado():
    """Si persistencia reporta duplicado (O-05), no se invoca al extractor."""
    extractor = MockExtractorClient()
    persistence = DuplicatePersistence()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )

    payload = _base_payload()

    with pytest.raises(HTTPException):
        await service.process_document(payload)

    # HTTP 409 se lanza desde el servicio; el extractor no se llamó.
    assert len(extractor.calls) == 0


@pytest.mark.asyncio
async def test_ingestion_page_count_bool_devuelve_failed():
    """page_count es booleano (subclase de int en Python) -> failed."""
    service, _extractor, persistence = _make_service(
        extractor_return={"content": "# Documento", "page_count": True}
    )
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.status == "failed"
    assert persistence.registered_payload is None


@pytest.mark.asyncio
async def test_ingestion_extractor_http_status_error_devuelve_failed():
    """ExtractorClient lanza httpx.HTTPStatusError -> failed sin registrar."""
    request = httpx.Request("POST", "http://extractor/api/v1/extract")
    response = httpx.Response(400, request=request)
    exc = httpx.HTTPStatusError("Bad Request", request=request, response=response)

    service, _extractor, persistence = _make_service(extractor_exc=exc)
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.status == "failed"
    assert persistence.registered_payload is None
