"""Pruebas del contrato uniforme de errores (issue O-16 / D7).

Cubre la matriz de traducción de errores de los microservicios Extractor y
Persistencia, errores de comunicación (timeout / conexión), validación de
entrada, excepción no controlada y servicio pausado.

Todas las pruebas utilizan respx para simular los servicios downstream, por lo
que no dependen de que los microservicios estén levantados.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.main import create_app
from app.services.validation import compute_sha256_hex

VALID_PDF = b"%PDF-1.4 prueba O-16"
CHECKSUM = compute_sha256_hex(VALID_PDF)
EXTRACTOR_BASE = settings.extractor_service_url
PERSISTENCE_BASE = settings.persistence_service_url
DOCUMENT_ID = "65f1a2b3-c4d5-e6f7-a8b9-c0d1e2f3a4b5"


def _fresh_client() -> TestClient:
    return TestClient(create_app())


def _assert_error_contract(
    response: Response,
    expected_status: int,
    expected_code: str | None = None,
    expected_detail_contains: str | None = None,
) -> None:
    """Verifica el contrato uniforme de errores y campos requeridos."""
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "detail" in body and body["detail"] != ""
    assert "code" in body and body["code"] != ""
    assert "request_id" in body and body["request_id"] is not None
    assert body["request_id"] != ""
    if expected_code is not None:
        assert body["code"] == expected_code
    if expected_detail_contains is not None:
        assert expected_detail_contains in body["detail"]
    # No filtrar stack traces ni información interna.
    assert "Traceback" not in str(body)
    assert "traceback" not in str(body).lower()
    assert "http://" not in str(body)


# ---------------------------------------------------------------------------
# PERSISTENCIA
# ---------------------------------------------------------------------------


class TestPersistenceErrors:
    @respx.mock
    def test_persistence_404_returns_404(self):
        """Persistencia 404 en GET -> orquestador 404."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/{DOCUMENT_ID}").mock(
            return_value=Response(404, json={"detail": "Not found"})
        )
        client = _fresh_client()
        response = client.get(
            f"/api/v1/documents/{DOCUMENT_ID}",
            headers={"X-Request-ID": "req-pers-404"},
        )
        _assert_error_contract(response, 404, "persistence_not_found")

    @respx.mock
    def test_persistence_409_returns_409_with_existing_id(self):
        """Persistencia 409 -> 409 con existing_id."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(
                200, json={"id": "doc-existente", "checksum": CHECKSUM}
            )
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-pers-409"},
        )
        body = response.json()
        _assert_error_contract(response, 409, "duplicate_document")
        assert body["existing_id"] == "doc-existente"

    @respx.mock
    def test_persistence_413_returns_413(self):
        """Persistencia 413 -> orquestador 413."""
        respx.post(f"{PERSISTENCE_BASE}/api/v1/documents").mock(
            return_value=Response(413, json={"detail": "Payload too large"})
        )
        # Forzar registro: chequeo 404, extractor 200, registro 413.
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(200, json={"content": "x", "page_count": 1})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-pers-413"},
        )
        _assert_error_contract(response, 413, "persistence_payload_too_large")

    @respx.mock
    def test_persistence_422_returns_422(self):
        """Persistencia 422 -> orquestador 422."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(422, json={"detail": "Unprocessable"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-pers-422"},
        )
        _assert_error_contract(response, 422, "persistence_unprocessable")

    @respx.mock
    def test_persistence_500_returns_502(self):
        """Persistencia 500 -> orquestador 502."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(500, json={"detail": "Internal error"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-pers-500"},
        )
        _assert_error_contract(response, 502, "persistence_error")

    @respx.mock
    def test_persistence_503_returns_502(self):
        """Persistencia 503 -> orquestador 502 (no se reintenta POST)."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(503, json={"detail": "Unavailable"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-pers-503"},
        )
        _assert_error_contract(response, 502, "persistence_error")


# ---------------------------------------------------------------------------
# EXTRACTOR
# ---------------------------------------------------------------------------


class TestExtractorErrors:
    @respx.mock
    def test_extractor_400_returns_422(self):
        """Extractor 400 -> orquestador 422."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(400, json={"detail": "Bad Request"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-ext-400"},
        )
        _assert_error_contract(response, 422, "extractor_unprocessable")

    @respx.mock
    def test_extractor_422_returns_422(self):
        """Extractor 422 -> orquestador 422."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(422, json={"detail": "Unprocessable PDF"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-ext-422"},
        )
        _assert_error_contract(response, 422, "extractor_unprocessable")

    @respx.mock
    def test_extractor_429_returns_429(self):
        """Extractor 429 -> orquestador 429."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(429, json={"detail": "Too Many Requests"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-ext-429"},
        )
        _assert_error_contract(response, 429, "extractor_too_many_requests")

    @respx.mock
    def test_extractor_500_returns_502(self):
        """Extractor 500 -> orquestador 502."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(500, json={"detail": "Internal error"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-ext-500"},
        )
        _assert_error_contract(response, 502, "extractor_error")

    @respx.mock
    def test_extractor_503_returns_502(self):
        """Extractor 503 -> orquestador 502 (POST no reintenta por status)."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            return_value=Response(503, json={"detail": "Service Unavailable"})
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-ext-503"},
        )
        _assert_error_contract(response, 502, "extractor_error")


# ---------------------------------------------------------------------------
# COMUNICACIÓN (timeout y conexión)
# ---------------------------------------------------------------------------


class TestCommunicationErrors:
    @respx.mock
    def test_persistence_timeout_returns_503(self):
        """Timeout de Persistencia -> 503."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            side_effect=httpx.ReadTimeout(
                "read timeout",
                request=httpx.Request(
                    "GET", f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}"
                ),
            )
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-comm-pers-timeout"},
        )
        _assert_error_contract(response, 503, "persistence_timeout")

    @respx.mock
    def test_extractor_timeout_returns_503(self):
        """Timeout de Extractor -> 503."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            side_effect=httpx.ReadTimeout(
                "read timeout",
                request=httpx.Request("POST", f"{EXTRACTOR_BASE}/api/v1/extract"),
            )
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-comm-ext-timeout"},
        )
        _assert_error_contract(response, 503, "extractor_timeout")

    @respx.mock
    def test_persistence_connection_error_returns_503(self):
        """Error de conexión de Persistencia -> 503."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            side_effect=httpx.ConnectError("connection failed")
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-comm-pers-conn"},
        )
        _assert_error_contract(response, 503, "persistence_connection_error")

    @respx.mock
    def test_extractor_connection_error_returns_503(self):
        """Error de conexión de Extractor -> 503."""
        respx.get(f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}").mock(
            return_value=Response(404, json={"detail": "not found"})
        )
        respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
            side_effect=httpx.ConnectError("connection failed")
        )
        client = _fresh_client()
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.pdf", VALID_PDF, "application/pdf")},
            headers={"X-Request-ID": "req-comm-ext-conn"},
        )
        _assert_error_contract(response, 503, "extractor_connection_error")


# ---------------------------------------------------------------------------
# OTROS (validación, excepción no controlada, pausa)
# ---------------------------------------------------------------------------


class TestOtherErrors:
    def test_input_validation_returns_422(self):
        """Validación de entrada (UUID inválido) -> 422."""
        client = _fresh_client()
        response = client.get(
            "/api/v1/documents/no-es-un-uuid-valido",
            headers={"X-Request-ID": "req-val-422"},
        )
        _assert_error_contract(response, 422, "unprocessable_entity")

    def test_unhandled_exception_returns_500(self):
        """Excepción no controlada -> 500 con mensaje genérico, sin stack trace."""
        app = create_app()

        @app.get("/test/unhandled")
        async def raise_unhandled():
            raise RuntimeError("algo inesperado")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/test/unhandled", headers={"X-Request-ID": "req-unhandled-500"}
        )
        _assert_error_contract(
            response, 500, "internal_error", "An unexpected error occurred."
        )

    @respx.mock
    def test_service_paused_returns_503(self):
        """Servicio pausado -> 503 con contrato de error JSON."""
        from app.core import middleware as mw

        mw._state = mw.STATE_PAUSED
        try:
            app = create_app()

            @app.get("/test/some-path")
            async def some_path():
                return {"ok": True}

            client = TestClient(app)
            response = client.get(
                "/test/some-path", headers={"X-Request-ID": "req-paused-503"}
            )

            assert response.status_code == 503
            assert response.headers["content-type"].startswith("application/json")
            body = response.json()
            assert body["detail"] == "Servicio temporalmente pausado"
            assert body["code"] == "service_paused"
            assert body["request_id"] == "req-paused-503"
            assert "Traceback" not in str(body)
        finally:
            mw._state = mw.STATE_RUNNING




