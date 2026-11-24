from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.core.middleware import request_id_var
from app.schemas.documents import DocumentUploadResponse
from app.schemas.errors import ErrorResponse
from app.services.downstream_errors import (
    DownstreamErrorTranslator,
    DownstreamService,
)

logger = logging.getLogger(__name__)


class IngestionService:
    """Application service coordinating document ingestion.
    It forwards the uploaded file metadata to the extractor service, then
    registers the document in the persistence service. All calls use the
    respective HTTP clients which implement retry/back‑off and propagate the
    X‑Request‑ID header.
    """

    def __init__(
        self,
        extractor_client: ExtractorClient | None = None,
        persistence_client: PersistenceClient | None = None,
    ) -> None:
        self.extractor = extractor_client or ExtractorClient()
        self.persistence = persistence_client or PersistenceClient()

    async def process_document(self, payload: dict[str, Any]) -> DocumentUploadResponse:
        """Process a new document upload end‑to‑end.
        Returns a `DocumentUploadResponse` with the persisted document fields.
        """
        checksum = payload.get("checksum")
        logger.info("Starting processing for document %s", checksum or "unknown")

        # Fail-fast duplicate check against persistence before invoking the extractor.
        if checksum:
            try:
                duplicate_info = await self.persistence.check_duplicate_by_checksum(
                    checksum
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    # Document does not exist in persistence, continue with extraction.
                    pass
                else:
                    # 409, 413, 422, 5xx y otros -> traducir segun matriz O-16.
                    raise DownstreamErrorTranslator.translate_persistence_status_error(
                        exc
                    ) from exc
            except httpx.RequestError as exc:
                logger.error(
                    "Persistence service communication failed for checksum %s: %s",
                    checksum,
                    exc,
                )
                raise DownstreamErrorTranslator.translate_communication_error(
                    exc, DownstreamService.PERSISTENCE
                ) from exc
            except Exception as exc:
                logger.exception(
                    "Unexpected error checking duplicate for checksum %s", checksum
                )
                raise DownstreamErrorTranslator.translate_unexpected_error(
                    DownstreamService.PERSISTENCE
                ) from exc
            else:
                # HTTP 200: document already exists, it is a duplicate.
                if not isinstance(duplicate_info, dict) or "id" not in duplicate_info:
                    logger.error(
                        "Persistence service returned invalid duplicate response "
                        "for checksum %s: %s",
                        checksum,
                        duplicate_info,
                    )
                    raise DownstreamErrorTranslator.translate_unexpected_error(
                        DownstreamService.PERSISTENCE
                    )
                existing_id = duplicate_info.get("id")
                logger.warning(
                    "Duplicate document detected: checksum=%s existing_id=%s",
                    checksum,
                    existing_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ErrorResponse(
                        code="duplicate_document",
                        detail=f"Document with checksum {checksum} already exists",
                        existing_id=existing_id,
                        request_id=request_id_var.get() or None,
                    ).model_dump(),
                )

        # Call extractor to extract text and page count from the PDF.
        filename = payload.get("filename", "unknown")
        pdf_bytes = payload.get("content", b"")

        try:
            extraction_result = await self.extractor.extract_document(
                filename=filename,
                pdf_bytes=pdf_bytes,
            )
        except httpx.HTTPStatusError as exc:
            logger.exception("Extractor call failed")
            raise DownstreamErrorTranslator.translate_extractor_status_error(
                exc
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Extractor service communication failed: %s", exc
            )
            raise DownstreamErrorTranslator.translate_communication_error(
                exc, DownstreamService.EXTRACTOR
            ) from exc
        except Exception as exc:
            logger.exception("Extractor call failed")
            raise DownstreamErrorTranslator.translate_unexpected_error(
                DownstreamService.EXTRACTOR
            ) from exc

        # Validate the extractor response contains the expected fields.
        if not isinstance(extraction_result, dict):
            logger.error(
                "Extractor returned invalid response type: %s",
                type(extraction_result),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ErrorResponse(
                    code="extractor_error",
                    detail="Extractor returned an invalid response",
                ).model_dump(),
            )

        extracted_text = extraction_result.get("content")
        page_count = extraction_result.get("page_count")

        if not isinstance(extracted_text, str):
            logger.error(
                "Extractor response missing or invalid 'content' field: %s",
                extracted_text,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ErrorResponse(
                    code="extractor_error",
                    detail="Extractor response missing or invalid 'content'",
                ).model_dump(),
            )

        if (
            not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 0
        ):
            logger.error(
                "Extractor response missing or invalid 'page_count' field: %s",
                page_count,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ErrorResponse(
                    code="extractor_error",
                    detail="Extractor response missing or invalid 'page_count'",
                ).model_dump(),
            )

        # Construir payload independiente para persistencia (sin enviar el binario PDF).
        persistence_payload = {
            "checksum_sha256": payload.get("checksum"),
            "filename": filename,
            "extracted_text": extracted_text,
            "page_count": page_count,
            "file_size_bytes": len(pdf_bytes),
            "metadata": payload.get("metadata", {}),
        }

        # Register in persistence service
        try:
            registration = await self.persistence.register_document(persistence_payload)
        except httpx.HTTPStatusError as exc:
            logger.exception("Persistence registration failed")
            raise DownstreamErrorTranslator.translate_persistence_status_error(
                exc
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Persistence service communication failed registering document: %s",
                exc,
            )
            raise DownstreamErrorTranslator.translate_communication_error(
                exc, DownstreamService.PERSISTENCE
            ) from exc
        except Exception as exc:
            logger.exception("Persistence registration failed")
            raise DownstreamErrorTranslator.translate_unexpected_error(
                DownstreamService.PERSISTENCE
            ) from exc

        if not isinstance(registration, dict) or "id" not in registration:
            logger.error(
                "Persistence service returned invalid registration response: %s",
                registration,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ErrorResponse(
                    code="persistence_error",
                    detail="Invalid response from persistence service",
                ).model_dump(),
            )

        document_id = registration["id"]
        if not isinstance(document_id, str) or not document_id:
            logger.error(
                "Persistence service returned invalid document id: %s",
                document_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ErrorResponse(
                    code="persistence_error",
                    detail="Invalid document id from persistence service",
                ).model_dump(),
            )

        created_at = registration.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            logger.error(
                "Persistence service returned invalid or missing created_at: %s",
                created_at,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ErrorResponse(
                    code="persistence_error",
                    detail=(
                        "Persistence service returned missing or invalid created_at"
                    ),
                ).model_dump(),
            )

        return DocumentUploadResponse(
            id=document_id,
            checksum=checksum,
            extracted_text=extracted_text,
            created_at=created_at,
            filename=filename,
            page_count=page_count,
            file_size_bytes=len(pdf_bytes),
        )

    async def list_documents(self, skip: int = 0, limit: int = 20) -> Any:
        """List documents with pagination.
        Delegates to PersistenceClient.GET /api/v1/documents?skip=&limit=.
        """
        try:
            raw_response = await self.persistence.list_documents(
                skip=skip,
                limit=limit,
            )

            # Persistence devuelve un objeto paginado con la clave "items".
            # Orchestrator conserva su contrato público de lista plana.
            if isinstance(raw_response, dict):
                items = raw_response.get("items")

                if not isinstance(items, list):
                    raise ValueError(
                        "Invalid paginated response from persistence service"
                    )

                return items

            # Compatibilidad con respuestas que ya sean listas planas.
            if isinstance(raw_response, list):
                return raw_response

            raise ValueError(
                "Invalid response format from persistence service"
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Persistence service returned unexpected status %d listing documents",
                exc.response.status_code,
            )
            raise DownstreamErrorTranslator.translate_persistence_status_error(
                exc
            ) from exc

        except httpx.RequestError as exc:
            logger.error(
                "Persistence service communication failed listing documents: %s",
                exc,
            )
            raise DownstreamErrorTranslator.translate_communication_error(
                exc, DownstreamService.PERSISTENCE
            ) from exc

        except Exception as exc:
            logger.exception("Unexpected error listing documents")
            raise DownstreamErrorTranslator.translate_unexpected_error(
                DownstreamService.PERSISTENCE
            ) from exc

    async def get_document(self, document_id: str) -> Any:
        """Get a document by ID.
        Delegates to PersistenceClient.GET /api/v1/documents/{document_id}.
        """
        try:
            return await self.persistence.get_document(document_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(
                    "Document %s not found in persistence service",
                    document_id,
                )
                raise DownstreamErrorTranslator._build_http_exception(
                    status.HTTP_404_NOT_FOUND,
                    "persistence_not_found",
                    f"Documento con ID {document_id} no encontrado",
                ) from exc
            logger.error(
                "Persistence service returned unexpected status %d for document %s",
                exc.response.status_code,
                document_id,
            )
            raise DownstreamErrorTranslator.translate_persistence_status_error(
                exc
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Persistence service communication failed for document %s: %s",
                document_id,
                exc,
            )
            raise DownstreamErrorTranslator.translate_communication_error(
                exc, DownstreamService.PERSISTENCE
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error getting document %s", document_id)
            raise DownstreamErrorTranslator.translate_unexpected_error(
                DownstreamService.PERSISTENCE
            ) from exc

    async def delete_document(self, document_id: str) -> Any:
        """Delete a document by ID.
        Delegates to PersistenceClient.DELETE /api/v1/documents/{document_id}.
        """
        try:
            return await self.persistence.delete_document(document_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(
                    "Document %s not found in persistence service for deletion",
                    document_id,
                )
                raise DownstreamErrorTranslator._build_http_exception(
                    status.HTTP_404_NOT_FOUND,
                    "persistence_not_found",
                    f"Documento con ID {document_id} no encontrado",
                ) from exc
            logger.error(
                "Persistence service returned unexpected status %d deleting "
                "document %s",
                exc.response.status_code,
                document_id,
            )
            raise DownstreamErrorTranslator.translate_persistence_status_error(
                exc
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Persistence service communication failed deleting document %s: %s",
                document_id,
                exc,
            )
            raise DownstreamErrorTranslator.translate_communication_error(
                exc, DownstreamService.PERSISTENCE
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error deleting document %s", document_id)
            raise DownstreamErrorTranslator.translate_unexpected_error(
                DownstreamService.PERSISTENCE
            ) from exc
