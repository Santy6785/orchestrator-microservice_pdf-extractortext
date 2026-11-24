import asyncio
import logging
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.core.config import settings
from app.schemas.errors import ErrorResponse

from .control_impl import shutdown, pause, resume, metrics

router = APIRouter(prefix="/control", tags=["control"])

logger = logging.getLogger(__name__)

# Estados que indican que una dependencia downstream está disponible.
# Coinciden con las respuestas reales de los microservicios Extractor
# ({"status": "ok"}) y Persistencia ({"status": "ready"}).
_EXTRACTOR_HEALTHY_STATUSES = {"ok"}
_PERSISTENCE_HEALTHY_STATUSES = {"ready"}


async def _probe_health(client, path: str, healthy_statuses) -> str:
    """Consulta el health de una dependencia y devuelve su estado.

    Cualquier error de transporte, timeout o respuesta HTTP fallida (tras los
    reintentos de ``BaseClient``) se informa como ``"unreachable"``. Del mismo
    modo, una respuesta HTTP exitosa cuyo campo ``status`` no indique que la
    dependencia está lista también se informa como ``"unreachable"``.

    Cada llamada gestiona sus propias excepciones, de modo que el fallo de una
    dependencia no afecta al estado reportado de la otra.
    """
    try:
        response = await client.get(path)
        status = response.get("status") if isinstance(response, dict) else response
        if status in healthy_statuses:
            return str(status)
    except Exception as exc:
        logger.warning(
            "Health check failed for %s: %s",
            path,
            exc,
            exc_info=True,
        )
    return "unreachable"


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": dict},
        503: {"model": ErrorResponse},
    },
)
async def health(request: Request) -> JSONResponse:
    """Health check that queries downstream services independently.

    Returns a JSON object with the orchestrator status and the health of the
    extractor and persistence services. Each downstream dependency is probed
    independently, so the failure of one does not mask the real status of the
    other.

    - HTTP 200 when both dependencies are available.
    - HTTP 503 when at least one dependency is not available.
    """
    extractor = ExtractorClient(timeout=settings.health_timeout_seconds)
    persistence = PersistenceClient(timeout=settings.health_timeout_seconds)
    try:
        extractor_health, persistence_health = await asyncio.gather(
            _probe_health(extractor, "/health", _EXTRACTOR_HEALTHY_STATUSES),
            _probe_health(
                persistence, "/health/ready", _PERSISTENCE_HEALTHY_STATUSES
            ),
        )
    finally:
        await extractor.close()
        await persistence.close()

    extractor_available = extractor_health != "unreachable"
    persistence_available = persistence_health != "unreachable"

    status_code = (
        status.HTTP_200_OK
        if extractor_available and persistence_available
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return JSONResponse(
        status_code=status_code,
        content={
            "orchestrator": "healthy",
            "extractor": extractor_health,
            "persistence": persistence_health,
        },
    )


router.include_router(shutdown)
router.include_router(pause)
router.include_router(resume)
router.include_router(metrics)
