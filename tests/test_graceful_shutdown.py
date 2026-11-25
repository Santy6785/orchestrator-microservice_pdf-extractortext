from __future__ import annotations

from unittest.mock import AsyncMock, patch

import asyncio

from fastapi.testclient import TestClient

from app.api.v1 import control_impl
from app.core import middleware as mw
from app.core.signals import register_signal_handlers
from app.dependencies import get_ingestion_service
from app.main import create_app, lifespan
from app.services.ingestion import IngestionService


class _DummyIngestionService(IngestionService):
    async def list_documents(self, skip: int = 0, limit: int = 20):
        return []


def _reset_lifecycle() -> None:
    mw.set_shutting_down(False)
    mw.set_pause(False)


def _fresh_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_ingestion_service] = lambda: _DummyIngestionService()
    return TestClient(app)


def test_shutdown_initiates_graceful_termination_and_blocks_new_requests():
    _reset_lifecycle()
    try:
        with patch.object(control_impl, "_send_termination_signal") as mock_kill:
            client = _fresh_client()
            response = client.post("/api/v1/control/shutdown")

            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "shutting_down"
            assert body["active_requests"] == 0
            assert "Apagado seguro iniciado" in body["message"]

            assert mw.is_shutting_down() is True
            assert mw.is_paused() is True
            mock_kill.assert_called_once()

            blocked = client.get(
                "/api/v1/documents/", headers={"X-Request-ID": "req-shutting-down"}
            )
            assert blocked.status_code == 503
            err = blocked.json()
            assert err["code"] == "service_shutting_down"
            assert err["request_id"] == "req-shutting-down"
    finally:
        _reset_lifecycle()


def test_shutdown_returns_409_when_already_shutting_down():
    _reset_lifecycle()
    try:
        with patch.object(control_impl, "_send_termination_signal"):
            client = _fresh_client()
            first = client.post("/api/v1/control/shutdown")
            assert first.status_code == 200

            second = client.post(
                "/api/v1/control/shutdown", headers={"X-Request-ID": "req-dup-shutdown"}
            )
            assert second.status_code == 409
            err = second.json()
            assert err["code"] == "conflict"
            assert err["request_id"] == "req-dup-shutdown"
    finally:
        _reset_lifecycle()


def test_resume_returns_409_during_shutdown():
    _reset_lifecycle()
    try:
        with patch.object(control_impl, "_send_termination_signal"):
            client = _fresh_client()
            client.post("/api/v1/control/shutdown")

            res = client.post("/api/v1/control/resume")
            assert res.status_code == 409
            assert res.json()["code"] == "conflict"
    finally:
        _reset_lifecycle()


def test_lifespan_registers_signal_handlers():
    """Verifica que el lifespan registra los manejadores de señal al arrancar."""
    _reset_lifecycle()
    try:
        with patch("app.main.register_signal_handlers") as mock_register:
            app = create_app()
            # lifespan se ejecuta al entrar al context manager de TestClient
            with TestClient(app) as client:
                mock_register.assert_called_once()
                # Verificar que se pasa el loop y un grace period
                args, kwargs = mock_register.call_args
                assert isinstance(args[0], asyncio.AbstractEventLoop)
                assert "grace_period_seconds" in kwargs
                assert kwargs["grace_period_seconds"] == 20.0
    finally:
        _reset_lifecycle()


def test_middleware_blocks_new_requests_when_shutting_down():
    """Verifica que el middleware rechaza nuevas solicitudes con 503 durante el apagado."""
    _reset_lifecycle()
    try:
        mw.set_shutting_down(True)
        mw.set_pause(True)

        client = _fresh_client()
        response = client.get(
            "/api/v1/documents/", headers={"X-Request-ID": "req-shutdown-block"}
        )

        assert response.status_code == 503
        err = response.json()
        assert err["code"] == "service_shutting_down"
        assert err["request_id"] == "req-shutdown-block"
    finally:
        _reset_lifecycle()


def test_active_requests_counter_increments_and_decrements():
    """Verifica que el contador de solicitudes activas se maneja correctamente."""
    _reset_lifecycle()
    try:
        assert mw.get_active_requests() == 0

        mw.set_pause(False)
        mw.set_shutting_down(False)

        # Simular una solicitud activa
        mw._active_requests += 1
        assert mw.get_active_requests() == 1

        mw._active_requests = max(0, mw._active_requests - 1)
        assert mw.get_active_requests() == 0
    finally:
        _reset_lifecycle()