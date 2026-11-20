import logging
from typing import Any

from app.clients.base import BaseClient
from app.core.config import settings

logger = logging.getLogger(__name__)


class PersistenceClient(BaseClient):
    """Client for the persistence microservice.
    URL configurada vía ``PERSISTENCE_SERVICE_URL`` en la instancia central de
    ``Settings``.
    """

    def __init__(self, service_url: str = settings.persistence_service_url):
        super().__init__(service_url=service_url)

    async def register_document(self, document_id: str, payload: dict[str, Any]) -> Any:
        """Create a new document record.
        Calls ``POST /api/v1/documents/{document_id}`` on the persistence service.
        """
        return await self.post(f"/api/v1/documents/{document_id}", json=payload)

    async def validate_document(self, document_id: str) -> bool:
        """Validate checksum/duplicate status.
        Calls ``GET /api/v1/documents/{document_id}/validate``.
        """
        result = await self.get(f"/api/v1/documents/{document_id}/validate")
        return result.get("valid", False)
