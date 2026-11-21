import hashlib

import httpx
import respx
from fastapi.testclient import TestClient

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

    async def validate_cross_service_integrity(self, document_id: str) -> bool:
        return True


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


def test_validate_document():
    response = client.get("/api/v1/documents/any-id/validate")
    assert response.status_code == 200
    assert response.json() == {"valid": True}


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


def test_upload_extractor_readtimeout_devuelve_502_con_detail():
    """Extractor lanza ReadTimeout en subida de PDF: endpoint responde 502 con detail no vacío y sin URLs internas."""
    real_service = IngestionService()
    app.dependency_overrides[get_ingestion_service] = lambda: real_service
    try:
        with respx.mock:
            respx.post("http://extractor/api/v1/extract").mock(
                side_effect=httpx.ReadTimeout("read timeout")
            )
            files = {"file": ("test.pdf", b"%PDF-1.4 test", "application/pdf")}
            response = client.post("/api/v1/documents/upload", files=files)
            assert response.status_code == 502
            body = response.json()
            assert "detail" in body and body["detail"] != ""
            # No se filtran URLs internas ni texto de excepción crudo que las contenga.
            assert "http://extractor" not in str(body)
    finally:
        app.dependency_overrides[get_ingestion_service] = lambda: (
            dummy_ingestion_service
        )
