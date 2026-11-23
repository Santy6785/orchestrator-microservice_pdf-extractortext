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

    def __init__(self, return_id: str = "doc-generado") -> None:
        self.registered_payload: dict[str, Any] | None = None
        self.return_id = return_id

    async def check_duplicate_by_checksum(self, checksum: str) -> Any:
        # Simula HTTP 404: no hay duplicado, el flujo continúa.
        request = httpx.Request("GET", "http://persistence/check")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    async def register_document(self, payload: dict[str, Any]) -> Any:
        self.registered_payload = payload
        return {"id": self.return_id, "created_at": "2026-01-01T00:00:00"}


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
    return {
        "filename": FILENAME,
        "content": VALID_PDF,
        "checksum": CHECKSUM,
        "metadata": {"source": "test"},
    }


@pytest.mark.asyncio
async def test_ingestion_extrae_filename_y_bytes_desde_payload():
    """El servicio extrae filename y content del payload y los pasa al extractor."""
    service, extractor, _persistence = _make_service()
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.id == "doc-generado"
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
async def test_ingestion_envia_checksum_sha256_a_persistencia():
    """El campo enviado a persistencia usa el nombre checksum_sha256."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["checksum_sha256"] == CHECKSUM
    assert "checksum" not in persistence.registered_payload


@pytest.mark.asyncio
async def test_ingestion_envia_filename_a_persistencia():
    """El nombre original del archivo se conserva en el payload de persistencia."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["filename"] == FILENAME


@pytest.mark.asyncio
async def test_ingestion_envia_texto_extraido_a_persistencia():
    """El texto extraído se envía correctamente a persistencia."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["extracted_text"] == "# Documento"


@pytest.mark.asyncio
async def test_ingestion_envia_page_count_a_persistencia():
    """La cantidad de páginas se envía correctamente a persistencia."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["page_count"] == 5


@pytest.mark.asyncio
async def test_ingestion_envia_file_size_bytes_a_persistencia():
    """file_size_bytes coincide con la longitud de los bytes originales."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["file_size_bytes"] == len(VALID_PDF)


@pytest.mark.asyncio
async def test_ingestion_envia_metadata_a_persistencia():
    """Los metadatos se conservan en el payload de persistencia."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["metadata"] == {"source": "test"}


@pytest.mark.asyncio
async def test_ingestion_metadata_vacio_por_defecto():
    """Si no hay metadatos, se envía un diccionario vacío."""
    service, _, persistence = _make_service()
    payload = {"filename": FILENAME, "content": VALID_PDF, "checksum": CHECKSUM}

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["metadata"] == {}


@pytest.mark.asyncio
async def test_ingestion_no_envia_binario_a_persistencia():
    """El binario original del PDF no se envía en el JSON a persistencia."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert "content" not in persistence.registered_payload
    assert "file" not in persistence.registered_payload


@pytest.mark.asyncio
async def test_ingestion_document_id_proviene_de_persistencia():
    """El ID de la respuesta es el que devuelve persistencia, no el filename."""
    service, _, _persistence = _make_service()
    payload = _base_payload()

    result = await service.process_document(payload)

    assert result.id == "doc-generado"
    assert result.id != FILENAME
    assert result.checksum == CHECKSUM
    assert result.filename == FILENAME
    assert result.extracted_text == "# Documento"
    assert result.page_count == 5
    assert result.file_size_bytes == len(VALID_PDF)
    assert result.created_at == "2026-01-01T00:00:00"


@pytest.mark.asyncio
async def test_ingestion_persistencia_id_vacio_devuelve_failed():
    """Si persistencia devuelve un ID vacío, el servicio falla y no informa éxito."""
    persistence = MockPersistenceClient(return_id="")
    extractor = MockExtractorClient()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_ingestion_persistencia_id_none_devuelve_failed():
    """Si persistencia devuelve id=None, el servicio falla y no informa éxito."""

    class PersistenciaIdNone(MockPersistenceClient):
        async def register_document(self, payload: dict[str, Any]) -> Any:
            self.registered_payload = payload
            return {"id": None, "created_at": "2026-01-01T00:00:00"}

    persistence = PersistenciaIdNone()
    extractor = MockExtractorClient()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_ingestion_persistencia_respuesta_invalida_devuelve_failed():
    """Si persistencia devuelve una respuesta sin id, el servicio falla
    sin inventar ID."""

    class PersistenciaSinId(MockPersistenceClient):
        async def register_document(self, payload: dict[str, Any]) -> Any:
            self.registered_payload = payload
            return {
                "checksum_sha256": "x",
                "created_at": "2026-01-01T00:00:00",
            }  # sin campo "id"

    persistence = PersistenciaSinId()
    extractor = MockExtractorClient()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_ingestion_persistencia_creado_at_faltante_devuelve_failed():
    """Si persistencia no devuelve created_at, el servicio falla sin inventar fecha."""

    class PersistenciaSinCreadoAt(MockPersistenceClient):
        async def register_document(self, payload: dict[str, Any]) -> Any:
            self.registered_payload = payload
            return {"id": "doc-generado"}  # sin campo "created_at"

    persistence = PersistenciaSinCreadoAt()
    extractor = MockExtractorClient()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502
    assert "created_at" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_ingestion_conserva_bytes_originales_en_payload():
    """payload['content'] conserva los bytes del PDF; no se sobrescribe."""
    service, _, _ = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert payload["content"] == VALID_PDF


@pytest.mark.asyncio
async def test_ingestion_guarda_extraido_en_nuevas_claves():
    """extracted_text y page_count se agregan al payload de persistencia
    sin perder contenido previo."""
    service, _, persistence = _make_service()
    payload = _base_payload()

    await service.process_document(payload)

    assert persistence.registered_payload is not None
    assert persistence.registered_payload["filename"] == FILENAME
    assert persistence.registered_payload["checksum_sha256"] == CHECKSUM
    assert persistence.registered_payload["extracted_text"] == "# Documento"
    assert persistence.registered_payload["page_count"] == 5
    assert persistence.registered_payload["file_size_bytes"] == len(VALID_PDF)
    assert persistence.registered_payload["metadata"] == {"source": "test"}
    # El payload original no se modifica con campos de persistencia.
    assert "extracted_text" not in payload
    assert "page_count" not in payload
    # El payload de persistencia es un diccionario independiente del original.
    assert persistence.registered_payload is not payload


@pytest.mark.asyncio
async def test_ingestion_extraer_sin_campos_obligatorios_devuelve_failed():
    """Respuesta sin 'content' o 'page_count' -> failed, sin continuar."""
    service, _extractor, persistence = _make_service(
        extractor_return={"content": "# Documento"}  # falta page_count
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502
    assert persistence.registered_payload is None  # no se registró en persistencia


@pytest.mark.asyncio
async def test_ingestion_extraer_con_tipos_invalidos_devuelve_failed():
    """content no string o page_count no int -> failed."""
    service, _, persistence = _make_service(
        extractor_return={"content": 123, "page_count": "cinco"}  # type: ignore[dict-item]
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502
    assert persistence.registered_payload is None


@pytest.mark.asyncio
async def test_ingestion_error_del_extractor_mantiene_comportamiento_de_error():
    """Excepción en el extractor -> HTTP 502 con detalle genérico, sin filtrar interna."""
    service, _, persistence = _make_service(
        extractor_exc=RuntimeError("extractor caído")
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail["code"] == "extractor_error"
    assert detail["message"] == "Error communicating with extractor service"
    # No se filtran detalles internos de la excepción.
    assert "extractor caído" not in str(detail)
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

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502
    assert persistence.registered_payload is None


@pytest.mark.asyncio
async def test_ingestion_extractor_http_status_error_devuelve_failed():
    """ExtractorClient lanza httpx.HTTPStatusError -> HTTP 502 sin registrar."""
    request = httpx.Request("POST", "http://extractor/api/v1/extract")
    response = httpx.Response(400, request=request)
    exc = httpx.HTTPStatusError("Bad Request", request=request, response=response)

    service, _extractor, persistence = _make_service(extractor_exc=exc)
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)
    assert exc_info.value.status_code == 502
    assert persistence.registered_payload is None


class MockPersistenceHttp503(MockPersistenceClient):
    """Persistencia que simula fallo HTTP 503 al registrar el documento."""

    async def register_document(self, payload: dict[str, Any]) -> Any:
        self.registered_payload = payload
        request = httpx.Request("POST", "http://persistence/api/v1/documents")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError(
            "Service Unavailable", request=request, response=response
        )


@pytest.mark.asyncio
async def test_ingestion_extractor_ok_persistencia_503_no_documento_creado():
    """Extractor OK + Persistencia HTTP 503 -> HTTP 502 con detail, sin
    documento creado."""
    extractor = MockExtractorClient()
    persistence = MockPersistenceHttp503()
    service = IngestionService(
        extractor_client=extractor,
        persistence_client=persistence,
    )
    payload = _base_payload()

    with pytest.raises(HTTPException) as exc_info:
        await service.process_document(payload)

    # Extractor fue llamado con el PDF.
    assert len(extractor.calls) == 1
    assert extractor.calls[0] == (FILENAME, VALID_PDF)

    # Persistencia fue llamada para registrar el documento (se intentó registrar).
    assert persistence.registered_payload is not None
    assert persistence.registered_payload["checksum_sha256"] == CHECKSUM
    assert persistence.registered_payload["extracted_text"] == "# Documento"
    assert persistence.registered_payload["page_count"] == 5

    # El orquestador responde con error HTTP 502 o 503.
    assert exc_info.value.status_code in (502, 503)

    # La respuesta de error contiene el campo detail.
    detail = exc_info.value.detail
    assert detail is not None
    assert isinstance(detail, dict)
    assert "code" in detail
    assert "message" in detail

    # No se devuelve un objeto de éxito: la excepción impide el return
    # de DocumentUploadResponse.
    # El mock de Persistencia lanzó HTTP 503 antes de devolver un id, p
    # or lo que el test no
    # observa un documento creado a partir de la respuesta del mock. El
    # mock no puede verificar
    # si Persistencia creó un registro internamente antes de fallar.
