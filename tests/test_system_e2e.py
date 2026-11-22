"""Capa 3 (Sistema): pruebas E2E contra los tres servicios levantados."""

from __future__ import annotations

import os
import time

import httpx
import pytest


def _orchestrator_base_url() -> str:
    return os.getenv("ORCHESTRATOR_SYSTEM_URL", "http://localhost:8000").rstrip("/")


def _minimal_pdf_bytes() -> bytes:
    unique_tag = f"SystemTest-{time.time_ns()}".encode("ascii")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
        b"% " + unique_tag + b"\n"
        b"%%EOF\n"
    )


@pytest.mark.system
def test_system_health_all_three_services_healthy():
    """Verifica con Docker que los tres servicios responden healthy."""
    with httpx.Client(base_url=_orchestrator_base_url(), timeout=10.0) as client:
        resp = client.get("/api/v1/control/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["orchestrator"] == "healthy"
        assert body["extractor"] == "healthy"
        assert body["persistence"] == "healthy"


@pytest.mark.system
def test_system_upload_get_list_delete_roundtrip():
    """Flujo E2E real entre Orquestador -> Extractor -> Persistencia."""
    pdf_bytes = _minimal_pdf_bytes()
    with httpx.Client(base_url=_orchestrator_base_url(), timeout=30.0) as client:
        upload = client.post(
            "/api/v1/documents/upload",
            files={"file": ("system_e2e.pdf", pdf_bytes, "application/pdf")},
        )
        assert upload.status_code == 200
        created = upload.json()
        doc_id = created["id"]

        fetched = client.get(f"/api/v1/documents/{doc_id}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == doc_id

        listed = client.get("/api/v1/documents/")
        assert listed.status_code == 200

        deleted = client.delete(f"/api/v1/documents/{doc_id}")
        assert deleted.status_code == 204
