import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from respx import MockRouter
from app.main import app
from app.services.ingestion import IngestionService
from app.schemas.documents import ProcessingResult

# Override the ingestion service dependency for testing
class DummyIngestionService:
    async def process_document(self, payload):
        return ProcessingResult(document_id="dummy-id", status="queued", detail=None)
    async def validate_cross_service_integrity(self, document_id: str) -> bool:
        return True

app.dependency_overrides["app.dependencies.get_ingestion_service"] = lambda: DummyIngestionService()

client = TestClient(app)

def test_upload_document():
    files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 202
    data = response.json()
    assert data["document_id"] == "dummy-id"
    assert data["status"] == "queued"

def test_validate_document():
    response = client.get("/api/v1/documents/any-id/validate")
    assert response.status_code == 200
    assert response.json() == {"valid": True}
