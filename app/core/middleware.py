import contextvars
import logging
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

from app.schemas.errors import ErrorResponse

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

_pause_flag = False
_shutting_down = False
_active_requests = 0


async def pause_middleware(request: Request, call_next):
    global _active_requests

    if not request.url.path.startswith("/api/v1/control/"):
        if _shutting_down or _pause_flag:
            request_id = request.headers.get("X-Request-ID") or getattr(
                request.state, "request_id", None
            )
            detail = (
                "Servicio en proceso de apagado"
                if _shutting_down
                else "Servicio temporalmente pausado"
            )
            code = "service_shutting_down" if _shutting_down else "service_paused"
            return JSONResponse(
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                content=ErrorResponse(
                    detail=detail,
                    code=code,
                    request_id=request_id,
                ).model_dump(),
            )

        _active_requests += 1
        try:
            return await call_next(request)
        finally:
            _active_requests = max(0, _active_requests - 1)

    return await call_next(request)


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    request_id_var.set(request_id)
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def set_pause(state: bool):
    global _pause_flag
    _pause_flag = state
    logging.getLogger(__name__).info("Service pause set to %s", state)


def is_paused() -> bool:
    return _pause_flag


def set_shutting_down(state: bool) -> None:
    global _shutting_down
    _shutting_down = state
    logging.getLogger(__name__).info("Service shutting_down set to %s", state)


def is_shutting_down() -> bool:
    return _shutting_down


def get_active_requests() -> int:
    return _active_requests