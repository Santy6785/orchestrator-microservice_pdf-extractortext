import os

# Las variables de entorno deben definirse antes de importar la app, porque
# `app.core.config.settings = Settings()` se instancia al importar y ahora
# requiere EXTRACTOR_SERVICE_URL y PERSISTENCE_SERVICE_URL (O-03).
os.environ["EXTRACTOR_SERVICE_URL"] = "http://extractor"
os.environ["PERSISTENCE_SERVICE_URL"] = "http://persistence:8000"

import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.main import app

client = TestClient(app)


@respx.mock
def test_health_endpoint_integration():
    # Mock downstream /health endpoints (URLs reales de O-03)
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )
    persistence_mock = respx.get("http://persistence:8000/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "healthy"
    assert data["persistence"] == "healthy"
    # Ensure both downstream services were called
    assert extractor_mock.called
    assert persistence_mock.called
