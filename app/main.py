from fastapi import FastAPI

from app.application.services.orchestrator import OrchestratorService
from app.application.ports.repository import DocumentRepositoryPort
from app.domain.entities import Document, ProcessingResult
from app.infrastructure.http_client import SimulatedHTTPClient, DocumentRepositoryInfrastructure
from app.infrastructure.repository import DocumentRepository


def create_app() -> FastAPI:
    """FastAPI application factory (Composition Root).

    Single composition root for dependency injection. All concrete
    infrastructure implementations are wired here. The presentation
    layer depends only on application ports and domain entities.
    """
    # Composition Root: create all concretions
    http_client = SimulatedHTTPClient()

    infra = DocumentRepositoryInfrastructure(http_client=http_client)
    repo = DocumentRepository(infrastructure=infra)

    orchestrator = OrchestratorService(http_client=http_client)

    # Application port concretions
    document_repo = DocumentRepository(infrastructure=infra)

    app = FastAPI(
        title="Orquestador Microservice",
        version="0.1.0",
        description="N-Layers microservice orchestrator with FastAPI and uv",
    )

    # Include routes - dependencies are injected via FastAPI Depends
    from app.presentation.api.v1.endpoints import register_routes
    register_routes(app, orchestrator, document_repo)

    return app