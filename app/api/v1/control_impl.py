from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from app.schemas.errors import ErrorResponse
from app.core import middleware

# Shutdown endpoint (placeholder implementation)
shutdown = APIRouter()


@shutdown.post(
    "/shutdown",
    status_code=status.HTTP_200_OK,
    responses={500: {"model": ErrorResponse}},
)
async def shutdown_endpoint(request: Request) -> JSONResponse:
    """Trigger graceful shutdown.
    The orchestrator sets the pause flag; an external process manager
    should stop the service.
    """
    middleware.set_pause(True)
    return JSONResponse(content={"message": "Shutdown initiated"})


# Pause endpoint
pause = APIRouter()


@pause.post(
    "/pause",
    status_code=status.HTTP_200_OK,
    responses={500: {"model": ErrorResponse}},
)
async def pause_endpoint(request: Request) -> JSONResponse:
    middleware.set_pause(True)
    return JSONResponse(content={"message": "Service paused"})


# Resume endpoint
resume = APIRouter()


@resume.post(
    "/resume",
    status_code=status.HTTP_200_OK,
    responses={500: {"model": ErrorResponse}},
)
async def resume_endpoint(request: Request) -> JSONResponse:
    middleware.set_pause(False)
    return JSONResponse(content={"message": "Service resumed"})


# Metrics endpoint (placeholder)
metrics = APIRouter()


@metrics.get(
    "/metrics",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={500: {"model": ErrorResponse}},
)
async def metrics_endpoint(request: Request) -> dict:
    return {
        "uptime_seconds": 0,
        "requests_total": 0,
        "errors_total": 0,
    }
