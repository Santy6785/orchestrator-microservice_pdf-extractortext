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
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready", "database": "connected"})
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "healthy"
    assert data["persistence"] == "ready"
    # Ensure both downstream services were called
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_health_persistence_unhealthy_returns_200():
    # persistence responde 503 en /health/ready: el endpoint sigue 200 con
    # persistence no saludable (contrato actual: "unreachable").
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(
            503, json={"status": "unhealthy", "database": "disconnected"}
        )
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "unreachable"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_health_persistence_does_not_call_legacy_health_route():
    # Solo se mockea /health/ready. Si el código llamara a /health de
    # persistence, respx levantaría UnmockedError y este test fallaría.
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "healthy"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready", "database": "connected"})
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["persistence"] == "ready"
    assert extractor_mock.called
    assert persistence_mock.called
