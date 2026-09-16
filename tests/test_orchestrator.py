"""Behavioral tests for the OrchestratorService - Red-Green-Refactor cycle."""

from __future__ import annotations

import asyncio

import pytest

from app.application.services.orchestrator import OrchestratorService


class MockHTTPClient:
    """Mock HTTP client for testing the orchestrator."""

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.called = False

    async def post(self, path: str, **kwargs):  # type: ignore[override]
        self.called = True
        if self.should_fail:
            raise ConnectionError("Simulated downstream service failure")
        return {"status": "ok", "path": path, "valid": True}

    async def get(self, path: str, **kwargs):  # type: ignore[override]
        self.called = True
        if self.should_fail:
            raise ConnectionError("Simulated downstream service failure")
        return {"status": "ok", "path": path, "valid": True}


@pytest.mark.asyncio
async def test_orchestrator_process_document_success():
    """RED-GREEN: Test that orchestrator processes a document successfully."""
    # Arrange
    http_client = MockHTTPClient(should_fail=False)
    service = OrchestratorService(http_client=http_client)

    # Act
    result = await service.process_document("doc-001", {"key": "value"})

    # Assert - behavioral: verify the result reflects successful processing
    assert result.document_id == "doc-001"
    assert result.status == "processed"
    assert "successfully" in result.message
    assert result.message is not None


@pytest.mark.asyncio
async def test_orchestrator_process_document_failure():
    """RED-GREEN: Test that orchestrator handles downstream service failures."""
    # Arrange
    http_client = MockHTTPClient(should_fail=True)
    service = OrchestratorService(http_client=http_client)

    # Act
    result = await service.process_document("doc-001", {"key": "value"})

    # Assert - behavioral: verify failure is captured and reported
    assert result.document_id == "doc-001"
    assert result.status == "failed"
    assert result.message is not None
    assert "failure" in result.message.lower()


@pytest.mark.asyncio
async def test_orchestrator_validate_cross_service_integrity():
    """RED-GREEN: Test orchestrator cross-service integrity validation."""
    # Arrange
    http_client = MockHTTPClient(should_fail=False)
    service = OrchestratorService(http_client=http_client)

    # Act
    result = await service.validate_cross_service_integrity("doc-001")

    # Assert - behavioral: verify integrity check result
    assert result is True


@pytest.mark.asyncio
async def test_orchestrator_validate_cross_service_integrity_failure():
    """RED-GREEN: Test orchestrator handles validation failure gracefully."""
    # Arrange
    http_client = MockHTTPClient(should_fail=True)
    service = OrchestratorService(http_client=http_client)

    # Act
    result = await service.validate_cross_service_integrity("doc-001")

    # Assert - behavioral: verify failure is handled
    assert result is False