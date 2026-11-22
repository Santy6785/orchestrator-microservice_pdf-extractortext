"""Prueba de integración del flujo O-12: Upload -> 409 -> Delete -> Upload -> 200.

Verifica que eliminar un documento permite volver a cargar el mismo PDF.

Sigue el patron de tests/test_duplicate_check.py:
- IngestionService real (sin dobles de servicio).
- respx para interceptar llamadas HTTP a persistencia y extractor.
- TestClient sobre la app real, restaurando el override de dependencia al salir.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.dependencies import get_ingestion_service
from app.main import app
from app.services.ingestion import IngestionService
from app.services.validation import compute_sha256_hex

VALID_PDF = b"%PDF-1.4 test content for delete flow integration"
CHECKSUM = compute_sha256_hex(VALID_PDF)
PERSISTENCE_BASE = "http://persistence:8000"
EXTRACTOR_BASE = "http://extractor"


def _client_with_real_service():
    """Devuelve un TestClient que usa IngestionService real.

    Restaura el dependency_overrides previo al salir para no interferir con
    otros modulos de test.
    """
    previous_override = app.dependency_overrides.get(get_ingestion_service)
    app.dependency_overrides[get_ingestion_service] = lambda: IngestionService()
    client = TestClient(app)
    try:
        yield client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_ingestion_service, None)
        else:
            app.dependency_overrides[get_ingestion_service] = previous_override


@respx.mock
def test_upload_409_delete_upload_200_flow():
    """Flujo completo O-12: subir -> 409 duplicado -> borrar 204 -> subir de nuevo 200.

    Paso 1:  POST /upload con PDF valido. Persistencia responde 200 al
             chequeo por checksum (documento ya existe) -> HTTP 409.
    Paso 2:  Se obtiene existing_id del cuerpo del 409.
    Paso 3:  DELETE /documents/{id}. Persistencia responde 204 ->
             HTTP 204 con body vacio.
    Paso 4:  POST /upload con el mismo PDF. Persistencia responde 404 al
             chequeo por checksum (ya no existe) -> flujo continua ->
             extractor -> registro -> HTTP 200 con registro valido.
    """

    # Paso 1: chequeo por checksum retorna duplicado (200).
    # El segundo upload (despues del delete) llegara a la misma URL y
    # consumira la segunda respuesta (404).
    checksum_route = respx.get(
        f"{PERSISTENCE_BASE}/api/v1/documents/by-checksum/{CHECKSUM}"
    ).mock(
        side_effect=[
            Response(200, json={"id": "doc-existente", "checksum": CHECKSUM}),
            Response(404, json={"detail": "not found"}),
        ]
    )

    # Paso 3: DELETE al documento existente.
    delete_route = respx.delete(
        f"{PERSISTENCE_BASE}/api/v1/documents/doc-existente"
    ).mock(return_value=Response(204))

    # Paso 4: extractor y registro solo se invocan en el segundo upload exitoso.
    extractor_route = respx.post(f"{EXTRACTOR_BASE}/api/v1/extract").mock(
        return_value=Response(200, json={"content": "# Texto extraído", "page_count": 3})
    )
    register_route = respx.post(
        f"{PERSISTENCE_BASE}/api/v1/documents"
    ).mock(
        return_value=Response(
            201,
            json={"id": "doc-nuevo", "created_at": "2026-01-01T00:00:00"},
        )
    )

    # ------------------------------------------------------------------
    # Paso 1: primer upload -> HTTP 409 Conflict (documento duplicado)
    # ------------------------------------------------------------------
    for client in _client_with_real_service():
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", VALID_PDF, "application/pdf")},
        )

    assert response.status_code == 409, (
        f"Esperado 409, obtuvo {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "detail" in body
    assert body["detail"]["code"] == "duplicate_document"
    existing_id = body["detail"]["existing_id"]
    assert existing_id == "doc-existente"
    assert checksum_route.called
    assert checksum_route.call_count == 1

    # ------------------------------------------------------------------
    # Paso 2 (ya hecho): existing_id obtenido del cuerpo del 409
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Paso 3: DELETE /documents/{id} -> HTTP 204 No Content, body vacio
    # ------------------------------------------------------------------
    for client in _client_with_real_service():
        response = client.delete(f"/api/v1/documents/{existing_id}")

    assert response.status_code == 204, (
        f"Esperado 204, obtuvo {response.status_code}: {response.text}"
    )
    assert response.content == b"", f"Esperado body vacio, obtuvo: {response.content!r}"
    assert delete_route.called
    assert delete_route.call_count == 1

    # ------------------------------------------------------------------
    # Paso 4: segundo upload del mismo PDF -> HTTP 200 OK
    # ------------------------------------------------------------------
    for client in _client_with_real_service():
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", VALID_PDF, "application/pdf")},
        )

    assert response.status_code == 200, (
        f"Esperado 200, obtuvo {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["id"] == "doc-nuevo"
    assert body["checksum"] == CHECKSUM
    assert body["filename"] == "test.pdf"
    assert body["page_count"] == 3
    assert body["file_size_bytes"] == len(VALID_PDF)
    assert body["extracted_text"] == "# Texto extraído"
    assert body["created_at"] == "2026-01-01T00:00:00"

    # ------------------------------------------------------------------
    # Verificacion de secuencia de llamadas entre componentes
    # ------------------------------------------------------------------
    assert checksum_route.call_count == 2, (
        f"Esperado 2 llamadas a by-checksum, obtuvo {checksum_route.call_count}"
    )
    assert delete_route.call_count == 1
    assert extractor_route.call_count == 1
    assert register_route.call_count == 1

    # El mismo checksum se mantuvo en ambos uploads.
    assert body["checksum"] == CHECKSUM
