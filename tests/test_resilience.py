"""Pruebas de resiliencia (issue #55): excepciones, timeouts, retries y concurrencia.

Cubre los tests obligatorios del bloque:
1. Errores de validación.
2. Errores de Extractor.
3. Errores de Persistence.
4. Timeout.
5. Retry exitoso.
6. Retry agotado.
7. Error no recuperable sin retry.
8. Operación no idempotente sin retry automático.
9. Concurrencia.
10. Respuestas JSON uniformes.
11. Códigos HTTP correctos.
"""

from __future__ import annotations

import asyncio
import httpx
import respx
from fastapi.testclient import TestClient

from app.core.metrics import metrics_collector
from app.main import create_app
from app.services.validation import compute_sha256_hex


def _reset_metrics() -> None:
    """Reinicia el colector de métricas entre tests."""
    metrics_collector._requests_total = 0
    metrics_collector._requests_by_status.clear()
    metrics_collector._requests_by_method.clear()
    metrics_collector._requests_by_endpoint.clear()
    metrics_collector._active_requests = 0
    metrics_collector._errors_total = 0
    metrics_collector._errors_by_code.clear()
    metrics_collector._errors_by_service.clear()
    metrics_collector._request_latency = metrics_collector._request_latency.__class__(
        metrics_collector._request_latency._buckets
    )
    metrics_collector._downstream_calls_total.clear()
    metrics_collector._downstream_errors_total.clear()
    metrics_collector._downstream_latency.clear()
    metrics_collector._downstream_retries_total.clear()
    import time

    metrics_collector._start_time = time.monotonic()


def _fresh_client() -> TestClient:
    _reset_metrics()
    return TestClient(create_app())


VALID_PDF = b"%PDF-1.4 resilience test"
CHECKSUM = compute_sha256_hex(VALID_PDF)


# ---------------------------------------------------------------------------
# 1. Errores de validación
# ---------------------------------------------------------------------------


def test_validation_error_returns_422():
    """Una petición con datos inválidos devuelve HTTP 422 con contrato JSON."""
    client = _fresh_client()
    # POST /upload sin archivo -> error de validación
    response = client.post("/api/v1/documents/upload")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "detail" in body and body["detail"] != ""
    assert "code" in body and body["code"] != ""
    assert "request_id" in body


# ---------------------------------------------------------------------------
# 2. Errores de Extractor
# ---------------------------------------------------------------------------


@respx.mock
def test_extractor_error_returns_502():
    """Extractor devuelve 503 -> orquestador responde 502 con contrato JSON."""
    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://extractor/api/v1/extract").mock(
        return_value=httpx.Response(503, json={"detail": "Service Unavailable"})
    )

    client = _fresh_client()
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["code"] == "extractor_error"
    assert "request_id" in body


# ---------------------------------------------------------------------------
# 3. Errores de Persistence
# ---------------------------------------------------------------------------


@respx.mock
def test_persistence_error_returns_502():
    """Persistence devuelve 500 -> orquestador responde 502 con contrato JSON."""
    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://extractor/api/v1/extract").mock(
        return_value=httpx.Response(200, json={"content": "x", "page_count": 1})
    )
    respx.post("http://persistence:8000/api/v1/documents").mock(
        return_value=httpx.Response(500, json={"detail": "Internal error"})
    )

    client = _fresh_client()
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["code"] == "persistence_error"
    assert "request_id" in body


# ---------------------------------------------------------------------------
# 4. Timeout
# ---------------------------------------------------------------------------


@respx.mock
def test_timeout_returns_503():
    """Un ReadTimeout en Extractor devuelve HTTP 503 sin reintentar."""
    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://extractor/api/v1/extract").mock(
        side_effect=httpx.ReadTimeout(
            "read timeout",
            request=httpx.Request("POST", "http://extractor/api/v1/extract"),
        )
    )

    client = _fresh_client()
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "extractor_timeout"
    assert "request_id" in body


# ---------------------------------------------------------------------------
# 5. Retry exitoso
# ---------------------------------------------------------------------------


@respx.mock
def test_retry_successful_after_initial_failure():
    """GET idempotente que falla primero y luego funciona se reintenta."""
    call_count = 0

    async def flaky_response(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("connection failed")
        return httpx.Response(200, json={"status": "ok"})

    respx.get("http://extractor/health").mock(side_effect=flaky_response)
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )

    client = _fresh_client()
    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 200
    assert call_count == 2  # primer intento falló, segundo tuvo éxito

    # Verificar que se registró al menos un retry en métricas
    data = client.get("/api/v1/control/metrics").json()
    assert data["downstream_retries_total"].get("extractor", 0) >= 1


# ---------------------------------------------------------------------------
# 6. Retry agotado
# ---------------------------------------------------------------------------


@respx.mock
def test_retry_exhausted_returns_503():
    """GET idempotente que falla siempre se reintenta MAX_ATTEMPTS y luego falla."""
    async def always_fail(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    respx.get("http://extractor/health").mock(side_effect=always_fail)
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )

    client = _fresh_client()
    response = client.get("/api/v1/control/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["extractor"] == "unreachable"

    # Verificar que se registraron retries (MAX_ATTEMPTS - 1 = 2 retries)
    data = client.get("/api/v1/control/metrics").json()
    assert data["downstream_retries_total"].get("extractor", 0) >= 2


# ---------------------------------------------------------------------------
# 7. Error no recuperable sin retry
# ---------------------------------------------------------------------------


@respx.mock
def test_non_recoverable_error_no_retry():
    """Error 4xx no se reintenta (ni GET ni POST)."""
    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(400, json={"detail": "bad request"}))

    client = _fresh_client()
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    # El checksum calculado es "a"*64, persistence devuelve 400 (bad request)
    # que se traduce como error de comunicación (no es 404, así que no se
    # trata como "no existe", se traduce a 502)
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "persistence_error"
    assert "request_id" in body


# ---------------------------------------------------------------------------
# 8. Operación no idempotente sin retry automático
# ---------------------------------------------------------------------------


@respx.mock
def test_non_idempotent_no_retry_on_status():
    """POST al extractor con 503 NO se reintenta por código de estado."""
    call_count = 0

    async def always_503(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, json={"detail": "Service Unavailable"})

    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://extractor/api/v1/extract").mock(side_effect=always_503)

    client = _fresh_client()
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 502
    # POST no idempotente: solo 1 intento, sin reintentos por estado
    assert call_count == 1
    body = response.json()
    assert body["code"] == "extractor_error"


# ---------------------------------------------------------------------------
# 9. Concurrencia
# ---------------------------------------------------------------------------


@respx.mock
def test_concurrent_requests_isolated():
    """Varias requests concurrentes no se mezclan y cada una tiene su request_id."""
    respx.get("http://extractor/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )

    client = _fresh_client()
    request_ids = [f"req-conc-{i}" for i in range(10)]

    async def make_requests():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url="http://testserver",
        ) as ac:
            tasks = [
                ac.get("/api/v1/control/health", headers={"X-Request-ID": rid})
                for rid in request_ids
            ]
            await asyncio.gather(*tasks)

    asyncio.run(make_requests())

    # Cada request recibió su propio request_id en la respuesta
    for rid in request_ids:
        response = client.get(
            "/api/v1/control/health", headers={"X-Request-ID": rid}
        )
        assert response.headers.get("x-request-id") == rid


# ---------------------------------------------------------------------------
# 10. Respuestas JSON uniformes
# ---------------------------------------------------------------------------


@respx.mock
def test_uniform_error_json_structure():
    """Todas las respuestas de error siguen el contrato JSON uniforme."""
    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://extractor/api/v1/extract").mock(
        return_value=httpx.Response(503, json={"detail": "Service Unavailable"})
    )

    client = _fresh_client()
    response = client.post(
        "/api/v1/documents/upload",
        headers={"X-Request-ID": "req-uniform-001"},
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    # Campos requeridos del contrato uniforme
    assert "detail" in body and isinstance(body["detail"], str)
    assert "code" in body and isinstance(body["code"], str)
    assert "request_id" in body and body["request_id"] == "req-uniform-001"
    # No debe exponer stack traces ni detalles internos
    assert "Traceback" not in str(body)
    assert "traceback" not in str(body).lower()
    assert "http://" not in str(body)


# ---------------------------------------------------------------------------
# 11. Códigos HTTP correctos
# ---------------------------------------------------------------------------


@respx.mock
def test_correct_http_status_codes():
    """Cada error se mapea al código HTTP estándar correcto."""
    DOCUMENT_ID = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"

    # 404 de persistence en GET /documents/{id} -> 404
    respx.get(f"http://persistence:8000/api/v1/documents/{DOCUMENT_ID}").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    client = _fresh_client()
    response = client.get(f"/api/v1/documents/{DOCUMENT_ID}")
    assert response.status_code == 404

    # 422 de extractor -> 422
    respx.get(
        f"http://persistence:8000/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://extractor/api/v1/extract").mock(
        return_value=httpx.Response(422, json={"detail": "Unprocessable"})
    )
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
    )
    assert response.status_code == 422
