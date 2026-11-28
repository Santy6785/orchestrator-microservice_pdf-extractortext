import os

# Las variables de entorno deben definirse antes de importar la app, porque
# `app.core.config.settings = Settings()` se instancia al importar y ahora
# requiere EXTRACTOR_SERVICE_URL y PERSISTENCE_SERVICE_URL (O-03).
os.environ["EXTRACTOR_SERVICE_URL"] = "http://extractor"
os.environ["PERSISTENCE_SERVICE_URL"] = "http://persistence:8000"

import asyncio
import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.main import app

client = TestClient(app)


@respx.mock
def test_health_endpoint_integration():
    # Mock downstream /health endpoints (URLs reales de O-03)
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready", "database": "connected"})
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "ok"
    assert data["persistence"] == "ready"
    # Ensure both downstream services were called
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_health_extractor_available_persistence_fails_returns_503():
    # CASO 3 (O-18): extractor responde correctamente, persistencia falla.
    # El endpoint devuelve HTTP 503. Extractor conserva su estado disponible
    # y persistencia aparece como unreachable (aislamiento de fallos).
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        side_effect=httpx.ConnectError("connection failed")
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "ok"
    assert data["persistence"] == "unreachable"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_health_persistence_does_not_call_legacy_health_route():
    # Solo se mockea /health/ready. Si el código llamara a /health de
    # persistence, respx levantaría UnmockedError y este test fallaría.
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
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


@respx.mock
def test_health_extractor_fails_persistence_available_returns_503():
    # CASO 2 (O-18): extractor falla, persistencia responde correctamente.
    # El endpoint devuelve HTTP 503. Extractor aparece como unreachable y
    # persistencia conserva su estado disponible (aislamiento de fallos).
    extractor_mock = respx.get("http://extractor/health").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready", "database": "connected"})
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "ready"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_health_both_dependencies_fail_returns_503():
    # CASO 4 (O-18): extractor y persistencia fallan.
    # El endpoint devuelve HTTP 503 y ambas dependencias aparecen como
    # unreachable.
    extractor_mock = respx.get("http://extractor/health").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        side_effect=httpx.ConnectError("connection failed")
    )

    response = client.get("/api/v1/control/health")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "unreachable"
    assert extractor_mock.called
    assert persistence_mock.called


def test_health_clientes_usan_health_timeout(monkeypatch):
    """El endpoint de health usa HEALTH_TIMEOUT_SECONDS, no el de
    extractor ni persistencia."""
    monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
    monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
    monkeypatch.setenv("HEALTH_TIMEOUT_SECONDS", "4.0")
    from app.core.config import Settings

    s = Settings()
    assert s.health_timeout_seconds == 4.0
    extractor = ExtractorClient(timeout=s.health_timeout_seconds)
    persistence = PersistenceClient(timeout=s.health_timeout_seconds)
    assert extractor.timeout == 4.0
    assert persistence.timeout == 4.0
    assert extractor.timeout != s.extractor_timeout_seconds
    assert persistence.timeout != s.persistence_timeout_seconds


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


@respx.mock
def test_liveness_healthy():
    """Liveness no llama a dependencias y devuelve 200."""
    response = client.get("/api/v1/control/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data == {"orchestrator": "alive"}


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@respx.mock
def test_readiness_healthy_all_dependencies():
    """Readiness devuelve 200 cuando Extractor y Persistencia responden bien."""
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready"})
    )

    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "ok"
    assert data["persistence"] == "ready"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_readiness_extractor_unhealthy():
    """Readiness devuelve 503 cuando Extractor no responde."""
    extractor_mock = respx.get("http://extractor/health").mock(
        side_effect=httpx.ConnectError("connection failed")
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready"})
    )

    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "ready"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_readiness_persistence_unhealthy():
    """Readiness devuelve 503 cuando Persistencia no responde."""
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        side_effect=httpx.ConnectError("connection failed")
    )

    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "ok"
    assert data["persistence"] == "unreachable"
    assert extractor_mock.called
    assert persistence_mock.called


@respx.mock
def test_readiness_extractor_timeout():
    """Readiness trata el timeout de Extractor como unreachable."""
    async def slow_response(*args, **kwargs):
        await asyncio.sleep(10)
        return Response(200, json={"status": "ok"})

    respx.get("http://extractor/health").mock(
        side_effect=slow_response
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready"})
    )

    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "ready"


@respx.mock
def test_readiness_persistence_timeout():
    """Readiness trata el timeout de Persistencia como unreachable."""
    async def slow_response(*args, **kwargs):
        await asyncio.sleep(10)
        return Response(200, json={"status": "ready"})

    respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        side_effect=slow_response
    )

    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "ok"
    assert data["persistence"] == "unreachable"


@respx.mock
def test_readiness_global_timeout_both_dependencies_unreachable():
    """El timeout global acota el chequeo y marca ambas dependencias como
    unreachable sin bloquear indefinidamente."""
    async def slow_response(*args, **kwargs):
        await asyncio.sleep(10)
        return Response(200, json={"status": "ok"})

    respx.get("http://extractor/health").mock(
        side_effect=slow_response
    )
    respx.get("http://persistence:8000/health/ready").mock(
        side_effect=slow_response
    )

    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["orchestrator"] == "healthy"
    assert data["extractor"] == "unreachable"
    assert data["persistence"] == "unreachable"


# ---------------------------------------------------------------------------
# Health (alias de readiness) - compatibilidad con Docker y Traefik
# ---------------------------------------------------------------------------


@respx.mock
def test_health_alias_matches_readiness():
    """GET /health devuelve lo mismo que GET /health/ready."""
    extractor_mock = respx.get("http://extractor/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    persistence_mock = respx.get("http://persistence:8000/health/ready").mock(
        return_value=Response(200, json={"status": "ready"})
    )

    response_health = client.get("/api/v1/control/health")
    response_ready = client.get("/api/v1/control/health/ready")

    assert response_health.status_code == response_ready.status_code == 200
    assert response_health.json() == response_ready.json()
    assert extractor_mock.called
    assert persistence_mock.called


# ---------------------------------------------------------------------------
# Health checks no quedan bloqueados (timeout global)
# ---------------------------------------------------------------------------


@respx.mock
def test_health_checks_do_not_block_indefinitely():
    """Con ambas dependencias lentas, el endpoint responde en tiempo
    acotado por el timeout global en lugar de bloquear para siempre."""
    import time

    async def very_slow_response(*args, **kwargs):
        await asyncio.sleep(30)
        return Response(200, json={"status": "ok"})

    respx.get("http://extractor/health").mock(side_effect=very_slow_response)
    respx.get("http://persistence:8000/health/ready").mock(
        side_effect=very_slow_response
    )

    start = time.monotonic()
    response = client.get("/api/v1/control/health/ready")
    elapsed = time.monotonic() - start

    assert response.status_code == 503
    # El timeout global es 5s; la respuesta debe llegar bien antes de 30s.
    assert elapsed < 10.0, f"El health check tardó {elapsed:.2f}s (demasiado)"
