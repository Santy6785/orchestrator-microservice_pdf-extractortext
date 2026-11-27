"""Tests unitarios para el contrato uniforme de errores (issue O-16 / D7).

Verifica que:
- HTTPException se traduce a JSON con {"detail", "code", "request_id"}.
- RequestValidationError devuelve HTTP 422 con el contrato uniforme.
- Excepciones no controladas devuelven HTTP 500 con mensaje genérico.
- El middleware de pausa devuelve JSON 503 (no texto plano).
- El request_id se propaga desde el header X-Request-ID al cuerpo del error.
- Todas las respuestas de error tienen Content-Type: application/json.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.errors import ErrorResponse


# ---------------------------------------------------------------------------
# Tests del esquema ErrorResponse
# ---------------------------------------------------------------------------


class TestErrorResponseSchema:
    def test_error_response_contract_fields(self):
        err = ErrorResponse(
            detail="Algo salió mal",
            code="bad_gateway",
            request_id="req-123",
        )
        data = err.model_dump()
        assert data == {
            "detail": "Algo salió mal",
            "code": "bad_gateway",
            "request_id": "req-123",
            "existing_id": None,
        }

    def test_error_response_with_existing_id(self):
        err = ErrorResponse(
            detail="Documento duplicado",
            code="duplicate_document",
            request_id="req-456",
            existing_id="doc-abc",
        )
        data = err.model_dump()
        assert data["existing_id"] == "doc-abc"
        assert data["code"] == "duplicate_document"

    def test_error_response_defaults(self):
        err = ErrorResponse(detail="Error", code="error")
        data = err.model_dump()
        assert data["request_id"] is None
        assert data["existing_id"] is None


# ---------------------------------------------------------------------------
# Tests de los exception handlers globales
# ---------------------------------------------------------------------------


def _make_client_with_handler():
    """Crea una app con un endpoint que lanza HTTPException para probar el handler."""
    app = create_app()

    @app.get("/test/http-exception")
    async def raise_http_exception():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorResponse(
                detail="Fallo downstream",
                code="extractor_error",
            ).model_dump(),
        )

    return app


class TestGlobalExceptionHandlers:
    def test_http_exception_structured_detail_returns_json_error_contract(self):
        """HTTPException con detail estructurado (dict con code) → contrato uniforme."""
        app = _make_client_with_handler()
        client = TestClient(app)

        response = client.get("/test/http-exception")

        assert response.status_code == 502
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["detail"] == "Fallo downstream"
        assert body["code"] == "extractor_error"
        assert "request_id" in body

    def test_http_exception_simple_string_detail_derives_code_from_status(self):
        """HTTPException con detail string → se deriva el code del status HTTP."""
        app = create_app()

        @app.get("/test/simple-error")
        async def raise_simple_error():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Documento no encontrado",
            )

        client = TestClient(app)
        response = client.get("/test/simple-error")

        assert response.status_code == 404
        body = response.json()
        assert body["detail"] == "Documento no encontrado"
        assert body["code"] == "not_found"
        assert "request_id" in body

    def test_request_validation_error_returns_422(self):
        """RequestValidationError → HTTP 422 con contrato uniforme."""
        app = create_app()

        @app.get("/test/validation-error")
        async def raise_validation_error():
            raise RequestValidationError(errors=[], body={})

        client = TestClient(app)
        response = client.get("/test/validation-error")

        assert response.status_code == 422
        body = response.json()
        assert body["detail"] == "Error de validación"
        assert body["code"] == "unprocessable_entity"
        assert "request_id" in body

    def test_unhandled_exception_returns_500_generic_message(self):
        """Excepción no controlada → HTTP 500 con mensaje genérico, sin stack trace."""
        app = create_app()

        @app.get("/test/unhandled")
        async def raise_unhandled():
            raise RuntimeError("algo inesperado")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test/unhandled")

        assert response.status_code == 500
        body = response.json()
        assert body["detail"] == "An unexpected error occurred."
        assert body["code"] == "internal_error"
        # No debe filtrar detalles internos ni stack traces.
        assert "RuntimeError" not in str(body)
        assert "algo inesperado" not in str(body)
        assert "request_id" in body

    def test_request_id_propagated_to_error_body(self):
        """El header X-Request-ID aparece en request_id del cuerpo del error."""
        app = _make_client_with_handler()
        client = TestClient(app)

        response = client.get(
            "/test/http-exception",
            headers={"X-Request-ID": "req-abc-123"},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["request_id"] == "req-abc-123"
        # También debe reflejarse en el header de respuesta.
        assert response.headers.get("X-Request-ID") == "req-abc-123"


# ---------------------------------------------------------------------------
# Tests del middleware de pausa (JSON, no texto plano)
# ---------------------------------------------------------------------------


class TestPauseMiddleware:
    def test_pause_middleware_returns_json_503(self):
        """Cuando el servicio está pausado, la respuesta es JSON 503."""
        from app.core import middleware as mw

        mw._state = mw.STATE_PAUSED
        try:
            app = create_app()

            @app.get("/test/some-path")
            async def some_path():
                return {"ok": True}

            client = TestClient(app)
            response = client.get("/test/some-path")

            assert response.status_code == 503
            assert response.headers["content-type"].startswith("application/json")
            body = response.json()
            assert body["detail"] == "Servicio temporalmente pausado"
            assert body["code"] == "service_paused"
            assert "request_id" in body
        finally:
            mw._state = mw.STATE_RUNNING


# ---------------------------------------------------------------------------
# Tests de que todas las respuestas de error son application/json
# ---------------------------------------------------------------------------


class TestErrorContentType:
    def test_all_error_responses_use_json(self):
        """400, 404, 409, 502, 503 devuelven Content-Type application/json."""

        for status_code, expected_code in [
            (400, "bad_request"),
            (404, "not_found"),
            (409, "conflict"),
            (502, "bad_gateway"),
            (503, "service_unavailable"),
        ]:

            def make_handler(sc=status_code, ec=expected_code):
                async def raise_with_code():
                    raise HTTPException(status_code=sc, detail="test error")

                return raise_with_code

            test_app = create_app()
            test_app.get(f"/test/code/{status_code}")(make_handler())

            c = TestClient(test_app)
            resp = c.get(f"/test/code/{status_code}")
            assert resp.status_code == status_code
            assert resp.headers["content-type"].startswith("application/json")
            body = resp.json()
            assert body["code"] == expected_code
            assert body["detail"] == "test error"
