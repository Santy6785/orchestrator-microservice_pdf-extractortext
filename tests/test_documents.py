import hashlib

import httpx
import respx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import Response

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.dependencies import get_ingestion_service
from app.main import app
from app.schemas.documents import DocumentUploadResponse
from app.services.ingestion import IngestionService
from app.services.validation import MAX_FILE_SIZE, compute_sha256_hex


# Override the ingestion service dependency for testing
class DummyIngestionService:
    last_payload: dict | None = None

    async def process_document(self, payload):
        self.last_payload = payload
        return DocumentUploadResponse(
            id="dummy-id",
            checksum=payload.get("checksum", ""),
            extracted_text="# dummy text",
            created_at="2026-01-01T00:00:00",
            filename=payload.get("filename", "unknown.pdf"),
            page_count=1,
            file_size_bytes=len(payload.get("content", b"")),
        )

    async def get_document(self, document_id: str):
        """Doble de prueba para get_document."""
        if document_id == "00000000-0000-0000-0000-000000000000":
            raise HTTPException(
                status_code=404,
                detail=f"Documento con ID {document_id} no encontrado",
            )
        return {
            "id": document_id,
            "checksum": (
                "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b"
            ),
            "extracted_text": "# texto extraído de prueba",
            "created_at": "2026-01-01T00:00:00",
        }

    async def list_documents(self, skip: int = 0, limit: int = 20):
        """Doble de prueba para list_documents."""
        return []

    async def delete_document(self, document_id: str):
        """Doble de prueba para delete_document."""
        return None


# Instancia compartida para poder inspeccionar el payload recibido desde los tests.
dummy_ingestion_service = DummyIngestionService()

app.dependency_overrides[get_ingestion_service] = lambda: dummy_ingestion_service

client = TestClient(app)


def test_upload_document():
    files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "dummy-id"
    assert data["filename"] == "test.pdf"


def test_upload_response_contract_fields_and_types():
    """Contrato O-08: respuesta 200 con los 7 campos y tipos esperados."""
    files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    data = response.json()

    expected_fields = {
        "id": str,
        "checksum": str,
        "extracted_text": str,
        "created_at": str,
        "filename": str,
        "page_count": int,
        "file_size_bytes": int,
    }
    assert set(data.keys()) == set(expected_fields.keys())
    for field, expected_type in expected_fields.items():
        assert field in data, f"Falta el campo '{field}' en la respuesta"
        if expected_type is int:
            assert type(data[field]) is int, (
                f"El campo '{field}' debe ser {expected_type.__name__} real, "
                f"fue {type(data[field]).__name__}"
            )
        else:
            assert isinstance(data[field], expected_type), (
                f"El campo '{field}' debe ser {expected_type.__name__}, "
                f"fue {type(data[field]).__name__}"
            )


def test_upload_document_payload_contains_valid_checksum():
    """El endpoint debe calcular un SHA-256 válido y pasarlo al servicio de ingesta."""
    content = b"%PDF-1.4 some content for checksum verification"
    files = {"file": ("test.pdf", content, "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200

    payload = dummy_ingestion_service.last_payload
    assert payload is not None
    assert "checksum" in payload
    checksum = payload["checksum"]
    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)
    assert checksum == checksum.lower()
    assert checksum == compute_sha256_hex(content)


def test_upload_document_at_size_limit():
    """Un archivo exactamente en el límite de 10 MB debe ser aceptado."""
    data = b"%PDF-" + b"%" * (MAX_FILE_SIZE - 5)
    files = {"file": ("limit.pdf", data, "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200


def test_upload_document_under_size_limit():
    """Un archivo menor a 10 MB debe ser aceptado."""
    data = b"%PDF-" + b"%" * 100
    files = {"file": ("small.pdf", data, "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200


def test_upload_document_over_size_limit():
    """Un archivo que excede 10 MB debe devolver HTTP 400."""
    data = b"%" * (MAX_FILE_SIZE + 1)
    files = {"file": ("big.pdf", data, "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400


def test_upload_document_over_size_includes_detail():
    """El error de tamaño excedido debe incluir un campo detail."""
    data = b"%" * (MAX_FILE_SIZE + 1)
    files = {"file": ("big.pdf", data, "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body


def test_upload_document_valid_magic_bytes():
    """Un contenido que comienza con %PDF- debe ser aceptado."""
    files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200


def test_upload_document_invalid_magic_bytes():
    """Un contenido que no comienza con %PDF- debe devolver HTTP 400."""
    files = {"file": ("notpdf.txt", b"plain text content", "text/plain")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body


def test_upload_document_empty_content():
    """Un archivo vacío debe ser rechazado."""
    files = {"file": ("empty.pdf", b"", "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body


def test_sha256_same_content_same_hash():
    """El hash de un mismo contenido siempre produce el mismo resultado."""
    content = b"%PDF-1.4 some content"
    first = compute_sha256_hex(content)
    second = compute_sha256_hex(content)
    assert first == second


def test_sha256_distinct_content_distinct_hash():
    """Contenidos distintos producen hashes distintos."""
    hash_a = compute_sha256_hex(b"%PDF-1.4 content A")
    hash_b = compute_sha256_hex(b"%PDF-1.4 content B")
    assert hash_a != hash_b


def test_sha256_length_is_64():
    """El resultado contiene exactamente 64 caracteres."""
    content = b"%PDF-1.4 content"
    result = compute_sha256_hex(content)
    assert len(result) == 64


def test_sha256_only_hex_characters():
    """El resultado contiene únicamente caracteres hexadecimales."""
    content = b"%PDF-1.4 content"
    result = compute_sha256_hex(content)
    assert all(c in "0123456789abcdef" for c in result)


def test_sha256_is_lowercase():
    """El resultado está en minúsculas."""
    content = b"%PDF-1.4 content"
    result = compute_sha256_hex(content)
    assert result == result.lower()


def test_sha256_exact_bytes():
    """El hash se calcula sobre el contenido exacto de los bytes."""
    content = b"%PDF-1.4 exact bytes"
    expected = hashlib.sha256(content).hexdigest()
    assert compute_sha256_hex(content) == expected


# ---------------------------------------------------------------------------
# Pruebas para GET /api/v1/documents/{document_id} (issue O-11)
# ---------------------------------------------------------------------------

VALID_UUID = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"
NOT_FOUND_UUID = "00000000-0000-0000-0000-000000000000"


def test_get_document_valid_uuid_returns_200():
    """O-11: UUID válido y documento existente -> HTTP 200 con los 4 campos."""
    response = client.get(f"/api/v1/documents/{VALID_UUID}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == VALID_UUID
    assert data["checksum"] == (
        "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b"
    )
    assert data["extracted_text"] == "# texto extraído de prueba"
    assert data["created_at"] == "2026-01-01T00:00:00"


def test_get_document_invalid_uuid_returns_422():
    """O-11: ID que no es un UUID válido -> HTTP 422."""
    response = client.get("/api/v1/documents/no-es-un-uuid-valido")
    assert response.status_code == 422


def test_get_document_not_found_returns_404():
    """O-11: UUID válido pero documento inexistente -> HTTP 404 con detail."""
    response = client.get(f"/api/v1/documents/{NOT_FOUND_UUID}")
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body


# ---------------------------------------------------------------------------
# Pruebas de ausencia de rutas retiradas (Issue O-13)
# ---------------------------------------------------------------------------


def test_get_validate_route_not_registered():
    """O-13: GET /api/v1/documents/{document_id}/validate debe haber sido retirada."""
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if "/validate" in path and "GET" in methods:
            raise AssertionError(
                f"La ruta GET {path} aún está registrada y debería haber sido eliminada"
            )


def test_put_document_route_not_registered():
    """O-13: PUT /api/v1/documents/{document_id} debe haber sido retirada."""
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if path == "/api/v1/documents/{document_id}" and "PUT" in methods:
            raise AssertionError(
                f"La ruta PUT {path} aún está registrada y debería haber sido eliminada"
            )


def test_removed_routes_not_in_openapi_schema():
    """O-13: Las rutas retiradas no deben aparecer en el schema OpenAPI generado."""
    openapi = app.openapi()
    paths = openapi.get("paths", {})

    assert "/api/v1/documents/{document_id}/validate" not in paths, (
        "GET /validate aún aparece en OpenAPI"
    )

    document_path = paths.get("/api/v1/documents/{document_id}", {})
    assert "put" not in document_path, "PUT /{document_id} aún aparece en OpenAPI"


# ---------------------------------------------------------------------------
# Pruebas de endpoints que siguen vigentes (Issue O-13)
# ---------------------------------------------------------------------------


def test_list_documents_returns_200():
    """GET /api/v1/documents/ (listado paginado) sigue vigente y responde 200."""
    response = client.get("/api/v1/documents/?skip=0&limit=20")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_delete_document_returns_204():
    """DELETE /api/v1/documents/{document_id} sigue vigente y responde 204."""
    response = client.delete(f"/api/v1/documents/{VALID_UUID}")
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Prueba de integración O-15: error del extractor sin filtrar información interna
# ---------------------------------------------------------------------------


def test_upload_extractor_readtimeout_devuelve_503_con_detail():
    """O-15: ReadTimeout del extractor devuelve 503 sin filtrar detalles internos."""

    content = b"%PDF-1.4 test"
    checksum = compute_sha256_hex(content)

    real_service = IngestionService(
        extractor_client=ExtractorClient(service_url="http://extractor"),
        persistence_client=PersistenceClient(
            service_url="http://persistence:8000"
        ),
    )
    app.dependency_overrides[get_ingestion_service] = lambda: real_service

    try:
        with respx.mock:
            # Persistence responde 404 (no es duplicado), llegando al extractor.
            persistence_route = respx.get(
                f"http://persistence:8000/api/v1/documents/by-checksum/{checksum}"
            ).mock(return_value=Response(404))

            # El extractor lanza ReadTimeout. Un POST con ReadTimeout no reintenta.
            extractor_route = respx.post(
                "http://extractor/api/v1/extract"
            ).mock(side_effect=httpx.ReadTimeout("read timeout"))

            files = {"file": ("test.pdf", content, "application/pdf")}
            response = client.post("/api/v1/documents/upload", files=files)

            # Matriz O-16: timeout de microservicio -> HTTP 503.
            assert response.status_code == 503
            body = response.json()
            assert "detail" in body and body["detail"] != ""
            assert body["code"] == "extractor_timeout"

            # No se filtran URLs internas ni el texto crudo de la excepción.
            assert "http://extractor" not in str(body)
            assert "read timeout" not in str(body)

            # El extractor se llamó una sola vez: POST ReadTimeout no reintenta (O-14).
            assert extractor_route.call_count == 1

            # Persistence se llamó una vez para comprobar duplicados.
            assert persistence_route.call_count == 1
    finally:
        app.dependency_overrides[get_ingestion_service] = (
            lambda: dummy_ingestion_service
        )