from __future__ import annotations

from typing import Any

from app.domain.entities import Document


class DocumentRepositoryPort:
    """Port (interface) for document repository operations.

    The presentation layer depends on this port, not on the concrete implementation.
    """

    async def save(self, document: Document) -> Document:
        raise NotImplementedError

    async def find_by_id(self, document_id: str) -> Document | None:
        raise NotImplementedError