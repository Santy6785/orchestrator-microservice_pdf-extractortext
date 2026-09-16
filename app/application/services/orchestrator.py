from __future__ import annotations

from typing import Any

from app.domain.entities import Document, ProcessingResult


class OrchestratorService:
    """Async orchestrator application service that coordinates domain operations.

    This service acts as an async orchestrator that can call other microservices
    via simulated HTTP clients, handling HTTP error codes appropriately.
    """

    def __init__(self, http_client: Any = None) -> None:
        self._http_client = http_client

    async def process_document(self, document_id: str, payload: dict[str, Any]) -> ProcessingResult:
        """Process a document by coordinating with downstream services.

        Args:
            document_id: Unique identifier of the document to process
            payload: Additional payload data for processing

        Returns:
            ProcessingResult with status and message
        """
        # Simulate calling downstream microservice
        if self._http_client:
            try:
                await self._http_client.post(
                    "/internal/process",
                    json={"document_id": document_id, "payload": payload},
                )
            except Exception as exc:
                return ProcessingResult(
                    document_id=document_id,
                    status="failed",
                    message=str(exc),
                )

        return ProcessingResult(
            document_id=document_id,
            status="processed",
            message="Document processed successfully",
        )

    async def validate_cross_service_integrity(self, document_id: str) -> bool:
        """Validate document integrity by calling external services.

        Returns:
            True if integrity check passes, False otherwise
        """
        if self._http_client:
            try:
                response = await self._http_client.get(
                    f"/internal/validate/{document_id}",
                )
                return response.get("valid", False) if isinstance(response, dict) else False
            except Exception:
                return False

        return True