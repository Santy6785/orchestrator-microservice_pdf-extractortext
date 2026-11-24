import asyncio
import logging
import os
import signal
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core import middleware
from app.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)

GRACE_PERIOD_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.05


def _send_termination_signal() -> None:
    sig = signal.SIGINT if os.name == "nt" else signal.SIGTERM
    os.kill(os.getpid(), sig)


async def _drain_and_terminate(grace_period_seconds: float = GRACE_PERIOD_SECONDS) -> None:
    deadline = time.monotonic() + grace_period_seconds
    while middleware.get_active_requests() > 0 and time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    remaining = middleware.get_active_requests()
    logger.info(
        "Terminating orchestrator process (remaining_active_requests=%d)",
        remaining,
    )
    _send_termination_signal()


shutdown = APIRouter()


@shutdown.post(
    "/shutdown",
    status_code=status.HTTP_200_OK,
    responses={
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def shutdown_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    if middleware.is_shutting_down():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "detail": "El proceso de apagado ya se encuentra en progreso.",
            },
        )

    active = middleware.get_active_requests()
    middleware.set_shutting_down(True)
    middleware.set_pause(True)
    background_tasks.add_task(_drain_and_terminate, GRACE_PERIOD_SECONDS)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "shutting_down",
            "active_requests": active,
            "message": "Apagado seguro iniciado. Esperando finalizacion de peticiones en curso.",
        },
    )


pause = APIRouter()


@pause.post(
    "/pause",
    status_code=status.HTTP_200_OK,
    responses={
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def pause_endpoint(request: Request) -> JSONResponse:
    if middleware.is_shutting_down():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "detail": "No se puede pausar: el servicio esta en proceso de apagado.",
            },
        )
    middleware.set_pause(True)
    return JSONResponse(content={"message": "Service paused"})


resume = APIRouter()


@resume.post(
    "/resume",
    status_code=status.HTTP_200_OK,
    responses={
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def resume_endpoint(request: Request) -> JSONResponse:
    if middleware.is_shutting_down():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "detail": "No se puede reanudar: el servicio esta en proceso de apagado.",
            },
        )
    middleware.set_pause(False)
    return JSONResponse(content={"message": "Service resumed"})


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