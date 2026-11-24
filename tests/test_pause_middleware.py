"""Tests para el middleware de pausa (issue O-17 / D8).

Verifica que:
- Las rutas de control (/api/v1/control/*) no son bloqueadas por la pausa.
- Las rutas de documentos son bloqueadas con HTTP 503 cuando está pausado.
- El 503 de pausa respeta el contrato uniforme de errores (O-16): detail, code,
  request_id y Content-Type application/json.
- Se puede reanudar el servicio incluso mientras está pausado.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.core import middleware as mw
from app.dependencies import get_ingestion_service
from app.main import create_app
from app.schemas.documents import DocumentUploadResponse
from app.services.ingestion import IngestionService


class _DummyIngestionService(IngestionService):
    """Doble de prueba que evita llamadas a servicios downstream reales."""

    async def process_document(self, payload):
        return DocumentUploadResponse(
            id="dummy-id",
            checksum=payload.get("checksum", ""),
            extracted_text="# dummy text",
            created_at="2026-01-01T00:00:00",
            filename=payload.get("filename", "unknown.pdf"),
            page_count=1,
            file_size_bytes=len(payload.get("content", b"")),
        )

    async def list_documents(self, skip: int = 0, limit: int = 20):
        return []

    async def get_document(self, document_id: str):
        return {
            "id": document_id,
            "checksum": "",
            "extracted_text": "",
            "created_at": "2026-01-01T00:00:00",
        }

    async def delete_document(self, document_id: str):
        return None


def _fresh_client() -> TestClient:
    """Crea un cliente con una app fresca y el ingestion service mockeado."""
    app = create_app()
    app.dependency_overrides[get_ingestion_service] = lambda: _DummyIngestionService()
    return TestClient(app)


def _reset_pause() -> None:
    """Asegura que el flag global de pausa quede inactivo entre tests."""
    mw.set_pause(False)


# ---------------------------------------------------------------------------
# TEST 1 — Aplicación sin pausa
# ---------------------------------------------------------------------------


def test_documents_not_blocked_when_not_paused():
    """Sin pausa, GET /api/v1/documents/ no es bloqueado por el middleware."""
    _reset_pause()
    try:
        client = _fresh_client()
        response = client.get("/api/v1/documents/")

        # El middleware de pausa no interviene; llega al endpoint
        # (doble) y responde 200.
        assert response.status_code == 200
        assert response.json() == []
    finally:
        _reset_pause()


# ---------------------------------------------------------------------------
# TEST 2 — Activar pausa
# ---------------------------------------------------------------------------


def test_pause_endpoint_activates_pause():
    """POST /api/v1/control/pause devuelve 200 y activa el flag de pausa."""
    _reset_pause()
    try:
        client = _fresh_client()
        response = client.post("/api/v1/control/pause")

        assert response.status_code == 200
        assert response.json() == {"message": "Service paused"}
        assert mw.is_paused() is True
    finally:
        _reset_pause()


# ---------------------------------------------------------------------------
# TEST 3 — Bloqueo de documentos con pausa activa
# ---------------------------------------------------------------------------


def test_documents_blocked_when_paused():
    """Con pausa activa, GET /api/v1/documents/ responde 503 JSON con contrato O-16."""
    mw.set_pause(True)
    try:
        client = _fresh_client()
        response = client.get("/api/v1/documents/")

        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/json")

        body = response.json()
        assert body["detail"] != ""
        assert body["code"] == "service_paused"
        assert body["request_id"] is not None
        assert body["request_id"] != ""

        # La cabecera de correlación también debe propagarse en la respuesta.
        assert response.headers.get("X-Request-ID") == body["request_id"]
    finally:
        _reset_pause()


# ---------------------------------------------------------------------------
# TEST 4 — Resume durante la pausa
# ---------------------------------------------------------------------------


def test_resume_endpoint_deactivates_pause():
    """POST /api/v1/control/resume devuelve 200 y desactiva el flag de pausa."""
    mw.set_pause(True)
    try:
        client = _fresh_client()
        response = client.post("/api/v1/control/resume")

        assert response.status_code == 200
        assert response.json() == {"message": "Service resumed"}
        assert mw.is_paused() is False
    finally:
        _reset_pause()


# ---------------------------------------------------------------------------
# TEST 5 — Health durante la pausa
# ---------------------------------------------------------------------------


@respx.mock
def test_health_not_blocked_when_paused():
    """Con pausa activa, GET /api/v1/control/health sigue respondiendo (no 503)."""
    respx.get("http://extractor/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    mw.set_pause(True)
    try:
        client = _fresh_client()
        response = client.get("/api/v1/control/health")

        # No es bloqueada por el middleware de pausa.
        assert response.status_code == 200
        body = response.json()
        assert body["orchestrator"] == "healthy"
    finally:
        _reset_pause()


# ---------------------------------------------------------------------------
# TEST 6 — Ciclo completo: pausa → documents 503 → health OK → resume → documents OK
# ---------------------------------------------------------------------------


@respx.mock
def test_full_pause_resume_cycle():
    """Ciclo completo de pausa y reanudación sobre las rutas reales."""
    respx.get("http://extractor/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://persistence:8000/health/ready").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    _reset_pause()
    try:
        client = _fresh_client()

        # 1. Sin pausa, documents responde 200.
        response = client.get("/api/v1/documents/")
        assert response.status_code == 200

        # 2. Activar pausa.
        response = client.post("/api/v1/control/pause")
        assert response.status_code == 200
        assert mw.is_paused() is True

        # 3. Con pausa, documents responde 503.
        response = client.get("/api/v1/documents/")
        assert response.status_code == 503
        assert response.json()["code"] == "service_paused"

        # 4. Con pausa, health sigue funcionando (no es bloqueado).
        response = client.get("/api/v1/control/health")
        assert response.status_code == 200
        assert response.json()["orchestrator"] == "healthy"

        # 5. Reanudar mientras está pausado.
        response = client.post("/api/v1/control/resume")
        assert response.status_code == 200
        assert mw.is_paused() is False

        # 6. Tras reanudar, documents vuelve a procesarse (no 503 por pausa).
        response = client.get("/api/v1/documents/")
        assert response.status_code == 200
    finally:
        _reset_pause()
