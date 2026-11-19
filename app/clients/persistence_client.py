import logging
from typing import Any

from app.clients.base import BaseClient

logger = logging.getLogger(__name__)


class PersistenceClient(BaseClient):
    """Client for the persistence microservice.
    Expected env var: PERSISTENCE_SERVICE_URL
    """
    env_var_name = "PERSISTENCE_SERVICE_URL"

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
