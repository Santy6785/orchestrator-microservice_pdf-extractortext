import os
import logging
from typing import Any, Dict
import uuid
import asyncio

import httpx
from app.core.middleware import request_id_var

logger = logging.getLogger(__name__)

class BaseClient:
    """Base HTTP client with retry, timeout and request‑ID propagation.
    Subclasses should set ``service_url`` to the appropriate env var value.
    """

    def __init__(self, timeout: float = 5.0, max_retries: int = 3, backoff_factor: float = 0.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.service_url = os.getenv(self.env_var_name, "http://localhost")
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.service_url}{path}"
        headers = kwargs.pop("headers", {})
        # Propagate request‑ID from contextvar if present
        request_id = request_id_var.get()
        if request_id:
            headers["X-Request-ID"] = request_id
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                if "application/json" in response.headers.get("content-type", ""):
                    return response.json()
                return response.text
            except (httpx.HTTPError, httpx.ConnectTimeout) as exc:
                logger.warning(
                    "%s request to %s failed on attempt %d/%d: %s",
                    method,
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.backoff_factor * (2 ** (attempt - 1)))

    async def get(self, path: str, **kwargs) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, json: Dict[str, Any] | None = None, **kwargs) -> Any:
        return await self._request("POST", path, json=json, **kwargs)

    async def close(self):
        await self._client.aclose()

class PersistenceClient(BaseClient):
    """Client for the persistence microservice.
    Expected env var: PERSISTENCE_SERVICE_URL
    """
    env_var_name = "PERSISTENCE_SERVICE_URL"

    async def register_document(self, document_id: str, payload: Dict[str, Any]) -> Any:
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
