# Dependency providers for FastAPI

from app.services.ingestion import IngestionService


def get_ingestion_service() -> IngestionService:
    """Factory for IngestionService used by FastAPI dependency injection.
    Allows easy overriding in tests.
    """
    return IngestionService()
