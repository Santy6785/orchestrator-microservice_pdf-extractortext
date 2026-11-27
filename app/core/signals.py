"""Manejadores de señales para apagado ordenado (graceful shutdown).

Registra manejadores de SIGTERM y SIGINT que:
1. Marcan el servicio como "apagando" para que el middleware rechace nuevas solicitudes.
2. Drenan las solicitudes activas hasta completarlas o vencer el tiempo de gracia.
3. Finalizan el proceso limpiamente.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time

from app.core import middleware

logger = logging.getLogger(__name__)

_shutdown_started = False


async def _drain_and_exit(grace_period_seconds: float = 20.0) -> None:
    """Drena solicitudes activas y finaliza el proceso.

    Se invoca ante recepción de SIGTERM/SIGINT. El middleware ya rechazará
    nuevas solicitudes (no-control) porque _shutting_down está en True.
    """
    global _shutdown_started

    if _shutdown_started:
        return
    _shutdown_started = True

    await middleware.set_shutting_down(True)
    await middleware.set_pause(True)

    deadline = time.monotonic() + grace_period_seconds
    while middleware.get_active_requests() > 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)

    remaining = middleware.get_active_requests()
    logger.info(
        "Graceful shutdown complete (remaining_active_requests=%d)", remaining
    )
    sys.exit(0 if remaining == 0 else 1)


def register_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    grace_period_seconds: float = 20.0,
) -> None:
    """Registra manejadores de SIGTERM y SIGINT en el bucle de eventos.

    En Windows add_signal_handler no está disponible; se ignora silenciosamente
    y el comportamiento de apagado depende de uvicorn/Docker.
    """
    async def _handle_signal() -> None:
        await _drain_and_exit(grace_period_seconds)

    try:
        loop.add_signal_handler(
            signal.SIGTERM, lambda: asyncio.create_task(_handle_signal())
        )
        loop.add_signal_handler(
            signal.SIGINT, lambda: asyncio.create_task(_handle_signal())
        )
        logger.debug("Signal handlers registered for SIGTERM/SIGINT")
    except NotImplementedError:
        logger.debug("Signal handlers not supported on this platform")
    except (ValueError, OSError) as exc:
        logger.warning("Could not register signal handlers: %s", exc)
