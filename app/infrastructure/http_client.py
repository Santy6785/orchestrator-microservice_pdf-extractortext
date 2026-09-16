from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


class SimulatedHTTPClient:
    """Simulated HTTP client for inter-microservice communication.

    Prepared to call other microservices with proper HTTP error handling.
    This client is injected via DI and can be replaced with real implementations.
    """

    def __init__(self, base_url: str = "http://localhost:8001", timeout: float = 5.0) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
        )

    async def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a GET request with HTTP error handling.

        Args:
            path: URL path to call
            **kwargs: Additional arguments for httpx client

        Returns:
            Response data as dictionary

        Raises:
        - HTTP error codes are translated to exceptions
        """
        response = await self._client.get(path, **kwargs)
        self._handle_response(response)
        return response.json()

    async def post(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a POST request with HTTP error handling.

        Args:
            path: URL path to call
            **kwargs: Additional arguments for httpx client

        Returns:
            Response data as dictionary

        Raises:
        - HTTP error codes are translated to exceptions
        """
        response = await self._client.post(path, **kwargs)
        self._handle_response(response)
        return response.json()

    async def put(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a PUT request with HTTP error handling.

        Args:
            path: URL path to call
            **kwargs: Additional arguments for httpx client

        Returns:
            Response data as dictionary

        Raises:
        - HTTP error codes are translated to exceptions
        """
        response = await self._client.put(path, **kwargs)
        self._handle_response(response)
        return response.json()

    async def delete(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a DELETE request with HTTP error handling.

        Args:
            path: URL path to call
            **kwargs: Additional arguments for httpx client

        Returns:
            Response data as dictionary

        Raises:
        - HTTP error codes are translated to exceptions
        """
        response = await self._client.delete(path, **kwargs)
        self._handle_response(response)
        return response.json()

    def _handle_response(self, response: httpx.Response) -> None:
        """Handle HTTP response, raising appropriate exceptions for error codes.

        Follows the resilience pattern of translating HTTP error codes
        into descriptive exceptions that the orchestrator can catch and handle.
        """
        if response.status_code >= 400:
            msg = f"HTTP {response.status_code}: {response.text}"
            raise httpx.HTTPStatusError(
                msg,
                request=response.request,
                response=response,
            )


class MockHTTPClient(SimulatedHTTPClient):
    """Mock HTTP client for testing that simulates downstream service responses.

    Used in tests to simulate various microservice scenarios without
    actual network calls. Prepared to return controlled responses
    for different HTTP status codes.
    """

    def __init__(self, mock_responses: Dict[str, Dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._mock_responses = mock_responses or {}
        self._call_count: Dict[str, int] = {}

    async def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Simulated GET with mock response handling."""
        self._call_count[path] = self._call_count.get(path, 0) + 1
        mock = self._mock_responses.get(path, {"status": "error", "message": "no mock"})
        return mock

    async def post(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Simulated POST with mock response handling."""
        self._call_count[path] = self._call_count.get(path, 0) + 1
        mock = self._mock_responses.get(path, {"status": "error", "message": "no mock"})
        return mock


class DocumentRepositoryInfrastructure:
    """Concrete repository implementation using infrastructure tools.

    Encapsulates all external concerns (database, file system, external APIs).
    The presentation layer only knows about the RepositoryPort interface.
    """

    def __init__(self, http_client: SimulatedHTTPClient | None = None) -> None:
        self._http_client = http_client
        self._storage: dict[str, Document] = {}

    async def save(self, document: Document) -> Document:
        """Save a document to infrastructure storage.

        Args:
            document: Document to persist

        Returns:
            The saved document
        """
        self._storage[document.id] = document
        return document

    async def find_by_id(self, document_id: str) -> Document | None:
        """Find a document by ID.

        Args:
            document_id: ID of the document to find

        Returns:
            Document if found, None otherwise
        """
        return self._storage.get(document_id)