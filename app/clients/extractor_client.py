import logging
from typing import Any

from app.clients.base import BaseClient
from app.core.config import settings

logger = logging.getLogger(__name__)


class ExtractorClient(BaseClient):
    """Client for the PDF extractor microservice.
    URL configurada vía ``EXTRACTOR_SERVICE_URL`` en la instancia central de
    ``Settings``.
    """

    def __init__(self, service_url: str = settings.extractor_service_url):
        super().__init__(service_url=service_url)

    async def extract_document(self, payload: dict[str, Any]) -> Any:
        """Call the extractor's `/extract` endpoint (POST).
        The payload should contain at least ``filename`` and optional ``metadata``.
        """
        return await self.post("/api/v1/extract", json=payload)
