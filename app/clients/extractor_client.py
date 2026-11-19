import logging
from typing import Any

from app.clients.base import BaseClient

logger = logging.getLogger(__name__)


class ExtractorClient(BaseClient):
    """Client for the PDF extractor microservice.
    Expected env var: EXTRACTOR_SERVICE_URL
    """
    env_var_name = "EXTRACTOR_SERVICE_URL"

    async def extract_document(self, payload: dict[str, Any]) -> Any:
        """Call the extractor's `/extract` endpoint (POST).
        The payload should contain at least ``filename`` and optional ``metadata``.
        """
        return await self.post("/api/v1/extract", json=payload)
