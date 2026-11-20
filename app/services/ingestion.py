from __future__ import annotations

from typing import Any, Dict
import logging

import httpx
from fastapi import HTTPException, status

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.schemas.documents import ProcessingResult
from app.schemas.errors import ErrorResponse

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

    async def process_document(self, payload: Dict[str, Any]) -> ProcessingResult:
        """Kick-off asynchronous processing of a new document.
        Returns a `ProcessingResult` with status *queued*.
        """
        document_id = payload.get("filename", "unknown")  # placeholder ID generation
        checksum = payload.get("checksum")
        logger.info("Starting processing for document %s", document_id)

        # Fail-fast duplicate check against persistence before invoking the extractor.
        if checksum:
            try:
                duplicate_info = await self.persistence.check_duplicate_by_checksum(checksum)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    # Document does not exist in persistence, continue with extraction.
                    pass
                else:
                    logger.error(
                        "Persistence service returned unexpected status %d for checksum %s",
                        exc.response.status_code,
                        checksum,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=ErrorResponse(
                            code="persistence_error",
                            message=f"Error communicating with persistence service: HTTP {exc.response.status_code}",
                        ).model_dump(),
                    )
            except httpx.RequestError as exc:
                logger.error(
                    "Persistence service communication failed for checksum %s: %s",
                    checksum,
                    exc,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=ErrorResponse(
                        code="persistence_error",
                        message="Error communicating with persistence service",
                    ).model_dump(),
                )
            except Exception as exc:
                logger.exception(
                    "Unexpected error checking duplicate for checksum %s: %s",
                    checksum,
                    exc,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=ErrorResponse(
                        code="persistence_error",
                        message="Error communicating with persistence service",
                    ).model_dump(),
                )
            else:
                # HTTP 200: document already exists, it is a duplicate.
                if not isinstance(duplicate_info, dict) or "document_id" not in duplicate_info:
                    logger.error(
                        "Persistence service returned invalid duplicate response for checksum %s: %s",
                        checksum,
                        duplicate_info,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=ErrorResponse(
                            code="persistence_error",
                            message="Invalid response from persistence service",
                        ).model_dump(),
                    )
                existing_id = duplicate_info.get("document_id")
                logger.warning(
                    "Duplicate document detected: checksum=%s existing_id=%s",
                    checksum,
                    existing_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ErrorResponse(
                        code="duplicate_document",
                        message=f"Document with checksum {checksum} already exists",
                        existing_id=existing_id,
                    ).model_dump(),
                )

        # Call extractor (simulated) – fire‑and‑forget
        try:
            await self.extractor.extract_document(payload)
        except Exception as exc:
            logger.exception("Extractor call failed: %s", exc)
            return ProcessingResult(document_id=document_id, status="failed", detail=str(exc))

        # Register in persistence service
        try:
            await self.persistence.register_document(document_id, payload)
        except Exception as exc:
            logger.exception("Persistence registration failed: %s", exc)
            return ProcessingResult(document_id=document_id, status="failed", detail=str(exc))

        return ProcessingResult(document_id=document_id, status="queued")

    async def validate_cross_service_integrity(self, document_id: str) -> bool:
        """Validate checksum and duplicate detection across downstream services.
        Returns ``True`` if the document passes all checks, ``False`` otherwise.
        """
        try:
            # In a real implementation we would call both services; here we
            # simply ask the persistence service for a validation endpoint.
            return await self.persistence.validate_document(document_id)
        except Exception as exc:
            logger.exception("Integrity validation failed: %s", exc)
            return False
