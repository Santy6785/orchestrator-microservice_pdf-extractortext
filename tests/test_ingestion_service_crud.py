"""Tests for IngestionService CRUD operations (issue O-10).

Utiliza dobles de prueba simples para evitar llamadas reales a Persistencia,
verificando que el servicio delega correctamente en PersistenceClient y
traduce los errores según las convenciones existentes.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.services.ingestion import IngestionService

DOCUMENT_ID = "65f1a2b3c4d5e6f7a8b9c0d1"
EXTRACTED_TEXT = "# Texto actualizado"


class MockPersistenceClientCrud:
    """Doble de prueba para PersistenceClient con métodos CRUD.

    Captura las llamadas a list_documents, get_document
    y delete_document sin red real.
    """

    def __init__(self) -> None:
        self.list_calls: list[tuple[int, int]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.exc: Exception | None = None

        # Valores de retorno por defecto
        self.list_return_value: Any = [
            {"id": "doc-1", "checksum": "aaa", "created_at": "2026-01-01"},
        ]
        self.get_return_value: Any = {
            "id": DOCUMENT_ID,
            "checksum": "abc",
            "extracted_text": "# Texto original",
            "created_at": "2026-01-01T00:00:00",
        }
        self.update_return_value: Any = {
            "id": DOCUMENT_ID,
            "checksum": "abc",
            "extracted_text": EXTRACTED_TEXT,
            "created_at": "2026-01-01T00:00:00",
        }

    async def list_documents(self, skip: int = 0, limit: int = 20) -> Any:
        self.list_calls.append((skip, limit))
        if self.exc is not None:
            raise self.exc
        return self.list_return_value

    async def get_document(self, document_id: str) -> Any:
        self.get_calls.append(document_id)
        if self.exc is not None:
            raise self.exc
        return self.get_return_value

    async def delete_document(self, document_id: str) -> Any:
        self.delete_calls.append(document_id)
        if self.exc is not None:
            raise self.exc
        return ""


def _make_service(
    persistence_exc: Exception | None = None,
) -> tuple[IngestionService, MockPersistenceClientCrud]:
    persistence = MockPersistenceClientCrud()
    if persistence_exc is not None:
        persistence.exc = persistence_exc
    service = IngestionService(persistence_client=persistence)
    return service, persistence


def _http_status_error(status_code: int = 404) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://persistence/test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_list_documents_delegates_to_persistence():
    """El servicio debe llamar a persistence.list_documents con skip y limit."""
    service, persistence = _make_service()
    resultado = await service.list_documents(skip=10, limit=25)

    assert persistence.list_calls == [(10, 25)]
    assert resultado == persistence.list_return_value


@pytest.mark.asyncio
async def test_ingestion_list_documents_default_args():
    """El servicio debe usar skip=0 y limit=20 por defecto."""
    service, persistence = _make_service()
    await service.list_documents()

    assert persistence.list_calls == [(0, 20)]


@pytest.mark.asyncio
async def test_ingestion_list_documents_returns_list():
    """El servicio debe retornar la lista tal como llega de persistencia."""
    service, persistence = _make_service()
    persistence.list_return_value = [
        {"id": "doc-1", "checksum": "aaa", "created_at": "2026-01-01"},
        {"id": "doc-2", "checksum": "bbb", "created_at": "2026-01-02"},
    ]
    resultado = await service.list_documents()

    assert isinstance(resultado, list)
    assert len(resultado) == 2
    assert resultado == persistence.list_return_value


@pytest.mark.asyncio
async def test_ingestion_list_documents_http_status_error_translates_to_502():
    """httpx.HTTPStatusError desde persistencia debe traducirse a HTTPException 502."""
    service, persistence = _make_service(persistence_exc=_http_status_error(502))

    with pytest.raises(HTTPException) as exc_info:
        await service.list_documents()
    assert exc_info.value.status_code == 502
    assert persistence.list_calls == [(0, 20)]


@pytest.mark.asyncio
async def test_ingestion_list_documents_request_error_translates_to_502():
    """httpx.RequestError desde persistencia debe traducirse a HTTPException 502."""
    service, _persistence = _make_service(
        persistence_exc=httpx.ConnectError("connection failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.list_documents()
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_ingestion_list_documents_unexpected_error_translates_to_502():
    """Cualquier excepción inesperada debe traducirse a HTTPException 502."""
    service, _persistence = _make_service(persistence_exc=RuntimeError("boom"))

    with pytest.raises(HTTPException) as exc_info:
        await service.list_documents()
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_get_document_delegates_to_persistence():
    """El servicio debe llamar a persistence.get_document con el document_id."""
    service, persistence = _make_service()
    resultado = await service.get_document(DOCUMENT_ID)

    assert persistence.get_calls == [DOCUMENT_ID]
    assert resultado == persistence.get_return_value


@pytest.mark.asyncio
async def test_ingestion_get_document_returns_full_document():
    """El servicio debe retornar el documento completo de persistencia."""
    service, persistence = _make_service()
    persistence.get_return_value = {
        "id": DOCUMENT_ID,
        "checksum": "c8ce4e97",
        "extracted_text": "Texto completo extraído del documento PDF...",
        "created_at": "2026-10-19T10:30:00",
    }
    resultado = await service.get_document(DOCUMENT_ID)

    assert resultado["id"] == DOCUMENT_ID
    assert "checksum" in resultado
    assert "extracted_text" in resultado
    assert "created_at" in resultado


@pytest.mark.asyncio
async def test_ingestion_get_document_persistence_404_translates_to_404():
    """HTTP 404 desde persistencia debe traducirse a HTTPException 404
    del orquestador."""
    service, persistence = _make_service(persistence_exc=_http_status_error(404))

    with pytest.raises(HTTPException) as exc_info:
        await service.get_document(DOCUMENT_ID)
    assert exc_info.value.status_code == 404
    detail = exc_info.value.detail
    assert detail == f"Documento con ID {DOCUMENT_ID} no encontrado"
    assert persistence.get_calls == [DOCUMENT_ID]


@pytest.mark.asyncio
async def test_ingestion_get_document_http_status_error_translates_to_502():
    """HTTP 500/502 desde persistencia debe traducirse a HTTPException 502."""
    service, persistence = _make_service(persistence_exc=_http_status_error(500))

    with pytest.raises(HTTPException) as exc_info:
        await service.get_document(DOCUMENT_ID)
    assert exc_info.value.status_code == 502
    assert persistence.get_calls == [DOCUMENT_ID]


@pytest.mark.asyncio
async def test_ingestion_get_document_request_error_translates_to_502():
    """httpx.RequestError desde persistencia debe traducirse a HTTPException 502."""
    service, _persistence = _make_service(
        persistence_exc=httpx.ConnectError("connection failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.get_document(DOCUMENT_ID)
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_delete_document_delegates_to_persistence():
    """El servicio debe llamar a persistence.delete_document con el document_id."""
    service, persistence = _make_service()
    resultado = await service.delete_document(DOCUMENT_ID)

    assert persistence.delete_calls == [DOCUMENT_ID]
    assert resultado == ""


@pytest.mark.asyncio
async def test_ingestion_delete_document_persistence_404_translates_to_404():
    """HTTP 404 desde persistencia debe traducirse a HTTPException 404
    del orquestador."""
    service, persistence = _make_service(persistence_exc=_http_status_error(404))

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_document(DOCUMENT_ID)
    assert exc_info.value.status_code == 404
    detail = exc_info.value.detail
    assert detail == f"Documento con ID {DOCUMENT_ID} no encontrado"
    assert persistence.delete_calls == [DOCUMENT_ID]


@pytest.mark.asyncio
async def test_ingestion_delete_document_http_status_error_translates_to_502():
    """HTTP 500/502 desde persistencia debe traducirse a HTTPException 502."""
    service, persistence = _make_service(persistence_exc=_http_status_error(500))

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_document(DOCUMENT_ID)
    assert exc_info.value.status_code == 502
    assert persistence.delete_calls == [DOCUMENT_ID]


@pytest.mark.asyncio
async def test_ingestion_delete_document_request_error_translates_to_502():
    """httpx.RequestError desde persistencia debe traducirse a HTTPException 502."""
    service, _persistence = _make_service(
        persistence_exc=httpx.ConnectError("connection failed")
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_document(DOCUMENT_ID)
    assert exc_info.value.status_code == 502
