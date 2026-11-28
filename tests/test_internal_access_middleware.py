"""Tests para el middleware de acceso interno a endpoints de control.

Verifica el comportamiento de ``internal_access_middleware``:

- Sin token (modo desarrollo): solo hosts internos (loopback / TestClient)
  pueden invocar los endpoints de control; un host externo recibe HTTP 403.
- Con token valido: se permite incluso desde un host externo.
- Con token invalido: HTTP 403.
- Las rutas que no son de control no se ven afectadas.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core import middleware as mw
from app.core.config import Settings, settings as app_settings
from app.main import create_app
from fastapi.testclient import TestClient


async def _call_next(request: Request) -> Response:
    return Response(status_code=200, content="ok")


def _make_request(
    path: str,
    host: str = "10.0.0.5",
    headers: dict[str, str] | None = None,
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": (host, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }
    if headers:
        scope["headers"] = [
            (k.lower().encode(), v.encode()) for k, v in headers.items()
        ]
    return Request(scope)


_CONTROL_ROUTES = [
    "/api/v1/control/pause",
    "/api/v1/control/resume",
    "/api/v1/control/shutdown",
    "/api/v1/control/metrics",
    "/api/v1/control/trace",
]


def _set_token(token: str | None) -> str | None:
    """Sobrescribe el token de settings y devuelve el valor previo para restaurar."""
    original = app_settings.internal_control_token
    app_settings.internal_control_token = token
    return original


def _reset_state() -> None:
    mw._state = mw.STATE_RUNNING


# ---------------------------------------------------------------------------
# Pruebas de unidad sobre el middleware (control directo del host cliente)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _CONTROL_ROUTES)
async def test_external_host_forbidden_without_token(path):
    """Sin token, un host externo (p. ej. otro contenedor Docker) recibe 403."""
    original = _set_token(None)
    _reset_state()
    try:
        request = _make_request(path, host="10.0.0.5")
        response = await mw.internal_access_middleware(request, _call_next)
        assert response.status_code == 403
        body = json.loads(response.body)
        assert body["code"] == "forbidden"
        assert "restringido" in body["detail"]
    finally:
        app_settings.internal_control_token = original
        _reset_state()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _CONTROL_ROUTES)
async def test_loopback_allowed_without_token(path):
    """Sin token, localhost (loopback) puede acceder."""
    original = _set_token(None)
    _reset_state()
    try:
        request = _make_request(path, host="127.0.0.1")
        response = await mw.internal_access_middleware(request, _call_next)
        assert response.status_code == 200
    finally:
        app_settings.internal_control_token = original
        _reset_state()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _CONTROL_ROUTES)
async def test_testserver_allowed_without_token(path):
    """TestClient llega como 'testserver', que esta en _INTERNAL_HOSTS."""
    original = _set_token(None)
    _reset_state()
    try:
        request = _make_request(path, host="testserver")
        response = await mw.internal_access_middleware(request, _call_next)
        assert response.status_code == 200
    finally:
        app_settings.internal_control_token = original
        _reset_state()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _CONTROL_ROUTES)
async def test_external_host_allowed_with_valid_token(path):
    """Con token valido, un host externo puede acceder."""
    original = _set_token("secret-token")
    _reset_state()
    try:
        request = _make_request(
            path,
            host="10.0.0.5",
            headers={"X-Internal-Token": "secret-token"},
        )
        response = await mw.internal_access_middleware(request, _call_next)
        assert response.status_code == 200
    finally:
        app_settings.internal_control_token = original
        _reset_state()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _CONTROL_ROUTES)
async def test_external_host_forbidden_with_invalid_token(path):
    """Con token invalido, un host externo recibe 403 aunque el token
    este configurado."""
    original = _set_token("secret-token")
    _reset_state()
    try:
        request = _make_request(
            path,
            host="10.0.0.5",
            headers={"X-Internal-Token": "wrong-token"},
        )
        response = await mw.internal_access_middleware(request, _call_next)
        assert response.status_code == 403
        body = json.loads(response.body)
        assert body["code"] == "forbidden"
    finally:
        app_settings.internal_control_token = original
        _reset_state()


@pytest.mark.asyncio
async def test_non_control_route_not_affected():
    """Las rutas que no son de control no son restringidas por este middleware."""
    original = _set_token(None)
    _reset_state()
    try:
        request = _make_request("/api/v1/documents/", host="10.0.0.5")
        response = await mw.internal_access_middleware(request, _call_next)
        assert response.status_code == 200
    finally:
        app_settings.internal_control_token = original
        _reset_state()


# ---------------------------------------------------------------------------
# Prueba de integracion con TestClient (host 'testserver', interno)
# ---------------------------------------------------------------------------


def test_control_endpoints_reachable_from_testclient_no_token():
    """Desde TestClient (testserver, interno) se accede a /pause y /metrics
    sin token."""
    original_token = _set_token(None)
    _reset_state()
    try:
        app = create_app()
        client = TestClient(app)
        try:
            response = client.post("/api/v1/control/pause")
            assert response.status_code in (200, 409)
            response = client.get("/api/v1/control/metrics")
            assert response.status_code == 200
        finally:
            client.close()
    finally:
        app_settings.internal_control_token = original_token
        _reset_state()


# ---------------------------------------------------------------------------
# Configuracion: en production el token es obligatorio
# ---------------------------------------------------------------------------


def test_settings_requires_internal_token_in_production():
    """Al arrancar con ENVIRONMENT=production y sin INTERNAL_CONTROL_TOKEN falla."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ.pop("INTERNAL_CONTROL_TOKEN", None)
    try:
        with pytest.raises(ValueError, match="INTERNAL_CONTROL_TOKEN es obligatorio"):
            Settings()
    finally:
        os.environ.pop("ENVIRONMENT", None)
        os.environ.pop("INTERNAL_CONTROL_TOKEN", None)


def test_settings_allows_missing_token_in_development():
    """En development (por defecto) se permite arrancar sin token."""
    os.environ.pop("ENVIRONMENT", None)
    os.environ.pop("INTERNAL_CONTROL_TOKEN", None)
    try:
        settings = Settings()
        assert settings.environment == "development"
        assert settings.internal_control_token is None
    finally:
        os.environ.pop("ENVIRONMENT", None)
        os.environ.pop("INTERNAL_CONTROL_TOKEN", None)
