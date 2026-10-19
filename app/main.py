from fastapi import FastAPI

from app.core import config, logging as core_logging, middleware
from app.api.v1 import documents, control


def create_app() -> FastAPI:
    """Application factory for the orchestrator microservice.

    - Registers routers for document management and control endpoints.
    - Applies middleware for request‑ID propagation and pause handling.
    - Configures logging based on environment variables.
    - Sets global exception handlers returning JSON error payloads.
    """
    # Configure logger early
    core_logging.configure_logging()
    import logging
    logger = logging.getLogger(__name__)

    app = FastAPI(title="Orquestador Microservice", version="0.1.0")

    # Middleware
    app.middleware("http")(middleware.request_id_middleware)
    app.middleware("http")(middleware.pause_middleware)

    # Include Routers
    app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
    app.include_router(control.router, prefix="/api/v1", tags=["control"])

    # Exception handling
    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        logger.exception("Unhandled exception: %s", exc)
        from fastapi.responses import JSONResponse
        from app.schemas.errors import ErrorResponse
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                code="internal_error",
                message="An unexpected error occurred.",
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )

    return app

# Create a single FastAPI instance for uvicorn
app = create_app()