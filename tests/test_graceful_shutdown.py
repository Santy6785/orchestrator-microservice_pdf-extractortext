from __future__ import annotations

from unittest.mock import patch

import asyncio
import threading

from fastapi.testclient import TestClient

from app.api.v1 import control_impl
from app.core import middleware as mw
from app.core import signals
from app.dependencies import get_ingestion_service
from app.main import create_app
from app.schemas.documents import DocumentUploadResponse
from app.services.ingestion import IngestionService


class _DummyIngestionService(IngestionService):
    async def list_documents(self, skip: int = 0, limit: int = 20):
        return []


class _SlowDummyIngestionService(IngestionService):
    """Dummy que demora en process_document para simular una request en vuelo."""

    def __init__(self, delay_seconds: float = 0.2):
        self.delay_seconds = delay_seconds

    async def process_document(self, payload):
        await asyncio.sleep(self.delay_seconds)
        return DocumentUploadResponse(
            id="dummy-id",
            checksum=payload.get("checksum", ""),
            extracted_text="# slow dummy text",
            created_at="2026-01-01T00:00:00",
            filename=payload.get("filename", "unknown.pdf"),
            page_count=1,
            file_size_bytes=len(payload.get("content", b"")),
        )

    async def list_documents(self, skip: int = 0, limit: int = 20):
        return []


def _reset_lifecycle() -> None:
    mw._state = mw.STATE_RUNNING
    signals._shutdown_started = False


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
            with TestClient(app):
                mock_register.assert_called_once()
                # Verificar que se pasa el loop y un grace period
                args, kwargs = mock_register.call_args
                assert isinstance(args[0], asyncio.AbstractEventLoop)
                assert "grace_period_seconds" in kwargs
                assert kwargs["grace_period_seconds"] == 20.0
    finally:
        _reset_lifecycle()


def test_middleware_blocks_new_requests_when_shutting_down():
    """Verifica que el middleware rechaza nuevas solicitudes con 503
    durante el apagado."""
    _reset_lifecycle()
    try:
        mw._state = mw.STATE_SHUTTING_DOWN

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

        mw._state = mw.STATE_RUNNING

        # Simular una solicitud activa
        mw._active_requests += 1
        assert mw.get_active_requests() == 1

        mw._active_requests = max(0, mw._active_requests - 1)
        assert mw.get_active_requests() == 0
    finally:
        _reset_lifecycle()


# ---------------------------------------------------------------------------
# Pruebas de comportamiento real de graceful shutdown (issue O-08)
# ---------------------------------------------------------------------------


def test_in_flight_request_completes_while_new_requests_blocked():
    """Una request ya iniciada termina durante el shutdown;
    las nuevas se bloquean."""
    _reset_lifecycle()
    try:
        import app.api.v1.control_impl as ci

        original_grace = ci.GRACE_PERIOD_SECONDS
        ci.GRACE_PERIOD_SECONDS = 0.5  # grace corto para el test

        app = create_app()
        app.dependency_overrides[get_ingestion_service] = lambda: (
            _SlowDummyIngestionService(delay_seconds=0.2)
        )
        client = TestClient(app)

        pdf_bytes = b"%PDF-1.4 fake content for graceful shutdown test"
        slow_result = {}

        def slow_upload():
            """Request en vuelo: tarda 0.2s, debe completar pese al shutdown."""
            try:
                resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("slow.pdf", pdf_bytes, "application/pdf")},
                )
                slow_result["status"] = resp.status_code
            except Exception as exc:  # pragma: no cover - diagnóstico
                slow_result["error"] = repr(exc)

        try:
            with patch.object(control_impl, "_send_termination_signal"):
                # 1. Lanzar la request lenta en un hilo paralelo (en vuelo).
                thread = threading.Thread(target=slow_upload)
                thread.start()
                # Pequeña espera para asegurar que entró y active_requests > 0.
                thread.join(timeout=0.05)

                # 2. Disparar shutdown mientras la request lenta sigue en vuelo.
                shutdown_resp = client.post("/api/v1/control/shutdown")
                assert shutdown_resp.status_code == 200

                # 3. Esperar a que la request en vuelo termine.
                thread.join(timeout=5)
                assert slow_result.get("status") == 200, (
                    "La request en vuelo debió completar con 200, obtuvo: "
                    f"{slow_result}"
                )

                # 4. Una request nueva (no-control) debe recibir 503.
                new_resp = client.get("/api/v1/documents/")
                assert new_resp.status_code == 503
                assert new_resp.json()["code"] == "service_shutting_down"
        finally:
            ci.GRACE_PERIOD_SECONDS = original_grace
            app.dependency_overrides = {}
    finally:
        _reset_lifecycle()


def test_control_routes_still_accessible_during_shutdown():
    """Durante el shutdown, las rutas de control (/metrics, /trace)
    siguen accesibles."""
    _reset_lifecycle()
    try:
        app = create_app()
        app.dependency_overrides[get_ingestion_service] = (
            lambda: _DummyIngestionService()
        )
        client = TestClient(app)

        with patch.object(control_impl, "_send_termination_signal"):
            shutdown_resp = client.post("/api/v1/control/shutdown")
            assert shutdown_resp.status_code == 200

            # Rutas de control: no bloqueadas por el middleware de pausa.
            metrics_resp = client.get("/api/v1/control/metrics")
            assert metrics_resp.status_code == 200

            trace_resp = client.get("/api/v1/control/trace")
            assert trace_resp.status_code == 200

            # Ruta normal: bloqueada con 503.
            blocked = client.get("/api/v1/documents/")
            assert blocked.status_code == 503
            assert blocked.json()["code"] == "service_shutting_down"
    finally:
        app.dependency_overrides = {}
        _reset_lifecycle()


def test_drain_terminates_after_grace_with_active_requests():
    """Si se supera el período de gracia con requests activas,
    el drenado termina igual."""
    _reset_lifecycle()
    try:
        mw._state = mw.STATE_SHUTTING_DOWN
        mw._active_requests = 1  # simula request que nunca termina

        with patch.object(control_impl, "_send_termination_signal") as mock_kill:
            asyncio.run(
                control_impl._drain_and_terminate(grace_period_seconds=0.1)
            )
            # Debe terminar aunque queden requests activas (grace vencido).
            mock_kill.assert_called_once()
    finally:
        _reset_lifecycle()


def test_shutdown_endpoint_returns_409_if_signal_shutdown_started():
    """Si el apagado ya fue iniciado por señal, el endpoint /shutdown
    rechaza con 409."""
    _reset_lifecycle()
    try:
        signals.mark_signal_shutdown_started()

        app = create_app()
        app.dependency_overrides[get_ingestion_service] = (
            lambda: _DummyIngestionService()
        )
        client = TestClient(app)

        resp = client.post("/api/v1/control/shutdown")
        assert resp.status_code == 409
        assert resp.json()["code"] == "conflict"
    finally:
        app.dependency_overrides = {}
        _reset_lifecycle()


def test_grace_period_coordination_with_docker():
    """Coordinación entre grace period de la app y stop_grace_period de Docker."""
    _reset_lifecycle()
    try:
        import app.api.v1.control_impl as ci
        from app.core import signals as sig_mod

        from pathlib import Path

        compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"
        compose_text = compose_path.read_text(encoding="utf-8")

        # Extraer stop_grace_period del docker-compose (formato simple YAML).
        stop_grace = None
        for line in compose_text.splitlines():
            if "stop_grace_period" in line:
                # Ejemplo: stop_grace_period: 20s
                parts = line.split(":", 1)
                if len(parts) == 2:
                    value = parts[1].strip().rstrip("s")
                    stop_grace = float(value)
                break

        assert (
            stop_grace is not None
        ), "No se encontró stop_grace_period en docker-compose.yml"
        assert stop_grace == 20.0, (
            f"Esperado stop_grace_period=20s, encontrado {stop_grace}s"
        )

        # El grace de la app (endpoint y signal handler) debe ser <= stop_grace_period
        # para que Docker no envíe SIGKILL antes de que la app termine su drenado.
        assert ci.GRACE_PERIOD_SECONDS <= stop_grace
        assert sig_mod._drain_and_exit.__defaults__[0] <= stop_grace  # default 20.0

        # Coherencia entre endpoint y signal handler.
        assert ci.GRACE_PERIOD_SECONDS == sig_mod._drain_and_exit.__defaults__[0]
        assert sig_mod._drain_and_exit.__defaults__[0] == 20.0
    finally:
        _reset_lifecycle()