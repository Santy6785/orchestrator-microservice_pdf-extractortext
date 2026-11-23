"""Capa 1 (Unitarias): validación, hash y mapeo de respuestas/errores."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from app.clients.base import BaseClient
from app.core.middleware import request_id_var
from app.schemas.documents import DocumentDetailResponse, DocumentUploadResponse
from app.schemas.errors import ErrorResponse
from app.services.validation import (
    MAX_FILE_SIZE,
    PDF_MAGIC_BYTES,
    compute_sha256_hex,
    validate_file_size,
    validate_pdf_magic_bytes,
)


class TestValidationUnit:
    def test_validate_file_size_accepts_exact_limit(self):
        validate_file_size(b"a" * MAX_FILE_SIZE)

    def test_validate_file_size_rejects_above_limit(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(b"a" * (MAX_FILE_SIZE + 1))
        assert exc_info.value.status_code == 400
        assert "10MB" in exc_info.value.detail

    def test_validate_pdf_magic_bytes_accepts_valid_header(self):
        validate_pdf_magic_bytes(PDF_MAGIC_BYTES + b"1.7\n...")

    @pytest.mark.parametrize("invalid_bytes", [b"", b"PK\x03\x04", b"%PDF", b"hello"])
    def test_validate_pdf_magic_bytes_rejects_invalid_headers(self, invalid_bytes):
        with pytest.raises(HTTPException) as exc_info:
            validate_pdf_magic_bytes(invalid_bytes)
        assert exc_info.value.status_code == 400


class TestHashingUnit:
    def test_compute_sha256_hex_matches_hashlib(self):
        sample = b"%PDF-1.4 sample payload for sha256"
        digest = compute_sha256_hex(sample)
        assert digest == hashlib.sha256(sample).hexdigest()
        assert len(digest) == 64
        assert digest == digest.lower()


class TestResponseMappingUnit:
    def test_document_upload_response_mapping(self):
        model = DocumentUploadResponse(
            id="doc-001",
            checksum="a" * 64,
            extracted_text="# Título",
            created_at="2026-11-22T12:00:00Z",
            filename="informe.pdf",
            page_count=4,
            file_size_bytes=2048,
        )
        dumped = model.model_dump()
        assert dumped["id"] == "doc-001"
        assert dumped["page_count"] == 4
        assert dumped["file_size_bytes"] == 2048

    def test_document_detail_response_mapping(self):
        detail = DocumentDetailResponse(
            id="doc-002",
            checksum="b" * 64,
            extracted_text="Contenido",
            created_at="2026-11-22T12:00:00Z",
        )
        assert detail.id == "doc-002"

    def test_error_response_mapping_with_and_without_existing_id(self):
        err = ErrorResponse(code="persistence_error", message="Fallo downstream")
        assert err.model_dump() == {
            "code": "persistence_error",
            "message": "Fallo downstream",
            "existing_id": None,
            "request_id": None,
        }
        dup = ErrorResponse(
            code="duplicate_document",
            message="Ya existe",
            existing_id="doc-999",
        )
        assert dup.existing_id == "doc-999"


@pytest.mark.asyncio
async def test_base_client_propagates_request_id_and_closes():
    token = request_id_var.set("req-unit-123")
    try:
        client = BaseClient(service_url="http://example.invalid")
        assert client.service_url == "http://example.invalid"
        await client.close()
    finally:
        request_id_var.reset(token)
