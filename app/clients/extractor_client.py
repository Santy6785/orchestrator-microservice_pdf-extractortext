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
        super().__init__(service_url=service_url, timeout=30.0)

    async def extract_document(self, filename: str, pdf_bytes: bytes) -> dict[str, Any]:
        """Call the extractor's `/extract` endpoint (POST) using multipart/form-data.

        Sends the PDF bytes in a form field named ``file`` with the original
        filename and MIME type ``application/pdf``. No additional JSON fields
        are sent; the extractor contract only requires the file part.

        Args:
            filename: Original name of the PDF file.
            pdf_bytes: Binary content of the PDF.

        Returns:
            Parsed JSON response from the extractor, expected to contain
            ``content`` and ``page_count`` fields.
        """
        files = {
            "file": (filename, pdf_bytes, "application/pdf"),
        }
        return await self.post("/api/v1/extract", files=files)
