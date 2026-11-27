import asyncio
import logging
import os
import signal
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core import middleware
from app.core.metrics import get_metrics_collector
from app.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)

GRACE_PERIOD_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.05


def _send_termination_signal() -> None:
    sig = signal.SIGINT if os.name == "nt" else signal.SIGTERM
    os.kill(os.getpid(), sig)


async def _drain_and_terminate(
    grace_period_seconds: float = GRACE_PERIOD_SECONDS,
) -> None:
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
    if not await middleware.set_shutting_down(True):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "detail": (
                    "El proceso de apagado ya se encuentra en progreso o el "
                    "servicio está detenido."
                ),
            },
        )

    await middleware.set_pause(True)

    active = middleware.get_active_requests()
    background_tasks.add_task(_drain_and_terminate, GRACE_PERIOD_SECONDS)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "shutting_down",
            "active_requests": active,
            "message": "Apagado seguro iniciado.",
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
    if not await middleware.set_pause(True):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "detail": (
                    "No se puede pausar: el servicio está en proceso de "
                    "apagado o detenido."
                ),
            },
        )
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
    if not await middleware.set_pause(False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "detail": "No se puede reanudar: servicio en apagado o detenido.",
            },
        )
    return JSONResponse(content={"message": "Service resumed"})


metrics = APIRouter()


@metrics.get(
    "/metrics",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": dict},
        403: {"model": ErrorResponse},
    },
)
async def metrics_endpoint(request: Request) -> dict:
    """Devuelve una instantánea de las métricas operativas del Orchestrator.

    Incluye: uptime, requests totales y por estado/método/endpoint, errores,
    latencias, llamadas y reintentos downstream, y requests activas.

    El acceso está restringido por ``internal_access_middleware`` (solo hosts
    internos o con ``X-Internal-Token`` válido).
    """
    collector = get_metrics_collector()
    data = await collector.snapshot()
    return JSONResponse(status_code=status.HTTP_200_OK, content=data)
