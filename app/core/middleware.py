import logging
from fastapi import Request, Response
import uuid
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

# Simple in‑memory pause flag (could be improved with a proper state manager)
_pause_flag = False

def pause_middleware(request: Request, call_next):
    """Reject requests with 503 when the service is paused.
    The /pause and /resume endpoints toggle the global _pause_flag.
    """
    if _pause_flag and request.url.path not in {"/api/v1/pause", "/api/v1/resume", "/api/v1/health"}:
        return Response(
            content="Service is paused",
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
        )
    response = await call_next(request)
    return response

def request_id_middleware(request: Request, call_next):
    """Assign a UUID request ID and propagate it via response headers."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

def set_pause(state: bool):
    global _pause_flag
    _pause_flag = state
    logging.getLogger(__name__).info("Service pause set to %s", state)

def is_paused() -> bool:
    return _pause_flag
