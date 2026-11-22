import asyncio
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from app.schemas.errors import ErrorResponse
from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient

router = APIRouter(prefix="/control", tags=["control"])

@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    responses={500: {"model": ErrorResponse}},
)
async def health(request: Request) -> JSONResponse:
    """Health check that queries downstream services.
    Returns a JSON object with the orchestrator status and the health of the
    extractor and persistence services.
    """
    extractor = ExtractorClient()
    persistence = PersistenceClient()
    try:
        extractor_resp, persistence_resp = await asyncio.gather(
            extractor.get("/health"), persistence.get("/api/v1/health")
        )
        # Extract status field if JSON contains it
        extractor_health = extractor_resp.get("status") if isinstance(extractor_resp, dict) else extractor_resp
        persistence_health = persistence_resp.get("status") if isinstance(persistence_resp, dict) else persistence_resp
    except Exception as exc:
        # If any downstream call fails, report unknown status
        extractor_health = "unreachable"
        persistence_health = "unreachable"
    finally:
        await extractor.close()
        await persistence.close()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "orchestrator": "healthy",
            "extractor": extractor_health,
            "persistence": persistence_health,
        },
    )

# The other control endpoints remain unchanged; they are imported from the
# existing file. To avoid duplication we will keep them in a separate module
# (`app/api/v1/control_impl.py`) and re-export here.

from .control_impl import shutdown, pause, resume, metrics

router.include_router(shutdown)
router.include_router(pause)
router.include_router(resume)
router.include_router(metrics)
