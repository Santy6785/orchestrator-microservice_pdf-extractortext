from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from fastapi import FastAPI
from app.application.services.orchestrator import OrchestratorService
from app.application.ports.repository import DocumentRepositoryPort
from app.domain.entities import Document, ProcessingResult

router = APIRouter(prefix="/documents", tags=["documents"])


def register_routes(
    app: FastAPI,
    orchestrator: OrchestratorService,
    repository: DocumentRepositoryPort,
) -> None:
    """Register routes with the given orchestrator and repository.

    This function is called from the composition root (main.py) so that
    the presentation layer never imports from infrastructure modules directly.
    The router is included in the application so its routes are active.
    """

    @router.post(
        "/",
        response_model=ProcessingResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def process_document() -> ProcessingResult:
        """Process a document via the async orchestrator service."""
        payload: dict[str, Any] = {"example": "payload"}
        return await orchestrator.process_document("doc-001", payload)

    @router.get(
        "/{document_id}/validate",
        response_model=dict[str, bool],
    )
    async def validate_document(
        document_id: str,
    ) -> dict[str, bool]:
        """Validate document integrity by calling external services."""
        result = await orchestrator.validate_cross_service_integrity(document_id)
        return {"valid": result}

    app.include_router(router)