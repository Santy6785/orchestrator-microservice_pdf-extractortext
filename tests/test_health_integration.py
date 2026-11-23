import os

os.environ.setdefault("EXTRACTOR_SERVICE_URL", "http://extractor")
os.environ.setdefault("PERSISTENCE_SERVICE_URL", "http://persistence:8000")

import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.main import create_app


@respx.mock
def test_health_endpoint_integration():
    """Consulta /health en extractor y /api/v1/health en persistencia."""
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )
    persistence_mock = respx.get("http://persistence:8000/api/v1/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )

    client = TestClient(create_app())
    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "healthy"
    assert data["persistence"] == "healthy"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_health_endpoint_downstream_unreachable():
    """Si un servicio downstream falla, informa estado unreachable sin caer en 500."""
    respx.get("http://extractor/health").mock(
        side_effect=httpx.ConnectError("extractor down")
    )
    respx.get("http://persistence:8000/api/v1/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )

    client = TestClient(create_app())
    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "unreachable"
