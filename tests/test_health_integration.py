import os
import pytest
from fastapi.testclient import TestClient
import respx
from httpx import Response
from app.main import app
from app.core.middleware import request_id_var

# Override environment variables for downstream services
os.environ["EXTRACTOR_SERVICE_URL"] = "http://mock-extractor"
os.environ["PERSISTENCE_SERVICE_URL"] = "http://mock-persistence"

client = TestClient(app)

@respx.mock
def test_health_endpoint_integration():
    # Mock downstream /health endpoints
    extractor_mock = respx.get("http://mock-extractor/health").mock(return_value=Response(200, json={"status": "healthy"}))
    persistence_mock = respx.get("http://mock-persistence/health").mock(return_value=Response(200, json={"status": "healthy"}))

    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "healthy"
    assert data["persistence"] == "healthy"
    # Ensure both downstream services were called
    assert extractor_mock.called
    assert persistence_mock.called
