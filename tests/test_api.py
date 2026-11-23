"""Behavioral tests for the API presentation layer - FastAPI endpoints."""

from __future__ import annotations


from app.main import create_app


def test_app_creation():
    """RED-GREEN: Test that the FastAPI app is created with correct configuration."""
    app = create_app()
    assert app is not None
    assert app.title == "Orquestador Microservice"


def test_app_has_router():
    """RED-GREEN: Test that the app includes the documents router."""
    app = create_app()
    # Check router registration by looking at route paths
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert any("/documents" in path for path in route_paths)
