from __future__ import annotations

from app.application.ports.repository import DocumentRepositoryPort
from app.domain.entities import Document
from app.infrastructure.http_client import DocumentRepositoryInfrastructure


class DocumentRepository(
    DocumentRepositoryPort,
):
    """Concrete implementation of DocumentRepositoryPort.

    Implements the port interface using the infrastructure layer.
    This class is the only one in infrastructure that the application layer
    directly depends on through the port abstraction.
    """

    def __init__(self, infrastructure: DocumentRepositoryInfrastructure | None = None) -> None:
        self._infrastructure = infrastructure or DocumentRepositoryInfrastructure()

    async def save(self, document: Document) -> Document:
        return await self._infrastructure.save(document)

    async def find_by_id(self, document_id: str) -> Document | None:
        return await self._infrastructure.find_by_id(document_id)