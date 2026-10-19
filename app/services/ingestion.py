from __future__ import annotations

from typing import Any, Dict
import logging

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.schemas.documents import ProcessingResult

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
        """Kick‑off asynchronous processing of a new document.
        Returns a `ProcessingResult` with status *queued*.
        """
        document_id = payload.get("filename", "unknown")  # placeholder ID generation
        logger.info("Starting processing for document %s", document_id)
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
