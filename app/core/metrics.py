"""Recopilador de métricas operativas en memoria para el Orchestrator.

Todas las métricas se mantienen en memoria (por instancia de proceso) y se
exponen a través de ``GET /api/v1/control/metrics``. No se utiliza ninguna
dependencia externa adicional.

Etiquetas permitidas (baja cardinalidad):
- ``method``: GET, POST, PUT, DELETE
- ``status_group``: 2xx, 4xx, 5xx
- ``endpoint_group``: documents, control, other
- ``service``: extractor, persistence
- ``outcome``: success, error, retry, exhausted
- ``code``: código de error legible por máquina
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any


# Buckets de latencia en milisegundos.
_LATENCY_BUCKETS_MS = (10, 50, 100, 250, 500, 1000, 2500, 5000)

# Grupos de endpoints permitidos (baja cardinalidad).
_ENDPOINT_GROUPS = {
    "/api/v1/documents": "documents",
    "/api/v1/control": "control",
}

# Métodos HTTP permitidos.
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})


def _endpoint_group(path: str) -> str:
    """Devuelve el grupo de endpoint para una ruta, o 'other'."""
    for prefix, group in _ENDPOINT_GROUPS.items():
        if path.startswith(prefix):
            return group
    return "other"


def _status_group(status_code: int) -> str:
    """Devuelve el grupo de código de estado (2xx, 4xx, 5xx)."""
    if 200 <= status_code < 300:
        return "2xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"


class _Histogram:
    """Histograma simple en memoria con buckets fijos."""

    def __init__(self, buckets: tuple[float, ...]) -> None:
        self._buckets = buckets
        self._counts = [0] * (len(buckets) + 1)
        self._sum = 0.0
        self._count = 0

    def observe(self, value: float) -> None:
        self._sum += value
        self._count += 1
        for i, bucket in enumerate(self._buckets):
            if value <= bucket:
                self._counts[i] += 1
                return
        self._counts[len(self._buckets)] += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "buckets": list(self._buckets),
            "counts": list(self._counts),
            "sum": round(self._sum, 3),
            "count": self._count,
        }


class MetricsCollector:
    """Recopilador de métricas operativas del Orchestrator.

    Thread-safe mediante ``asyncio.Lock``. Todas las métricas son contadores
    o histogramas simples en memoria; no hay dependencias externas.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._start_time = time.monotonic()

        # Contadores HTTP
        self._requests_total = 0
        self._requests_by_status: dict[str, int] = defaultdict(int)
        self._requests_by_method: dict[str, int] = defaultdict(int)
        self._requests_by_endpoint: dict[str, int] = defaultdict(int)
        self._active_requests = 0

        # Errores
        self._errors_total = 0
        self._errors_by_code: dict[str, int] = defaultdict(int)
        self._errors_by_service: dict[str, int] = defaultdict(int)

        # Latencia de requests HTTP
        self._request_latency = _Histogram(_LATENCY_BUCKETS_MS)

        # Downstream calls
        self._downstream_calls_total: dict[str, int] = defaultdict(int)
        self._downstream_errors_total: dict[str, int] = defaultdict(int)
        self._downstream_latency: dict[str, _Histogram] = {}

        # Retries downstream
        self._downstream_retries_total: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # Instrumentación de requests HTTP (llamada desde el middleware)
    # ------------------------------------------------------------------

    async def record_http_request(
        self,
        method: str,
        endpoint_group: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Registra una petición HTTP procesada."""
        async with self._lock:
            self._requests_total += 1
            self._requests_by_status[_status_group(status_code)] += 1
            if method in _ALLOWED_METHODS:
                self._requests_by_method[method] += 1
            self._requests_by_endpoint[endpoint_group] += 1
            self._request_latency.observe(duration_ms)

    async def increment_active_requests(self) -> None:
        async with self._lock:
            self._active_requests += 1

    async def decrement_active_requests(self) -> None:
        async with self._lock:
            self._active_requests = max(0, self._active_requests - 1)

    # ------------------------------------------------------------------
    # Instrumentación de errores
    # ------------------------------------------------------------------

    async def record_error(self, code: str, service: str | None = None) -> None:
        """Registra un error generado por el Orchestrator o un downstream."""
        async with self._lock:
            self._errors_total += 1
            self._errors_by_code[code] += 1
            if service:
                self._errors_by_service[service] += 1

    # ------------------------------------------------------------------
    # Instrumentación de llamadas downstream
    # ------------------------------------------------------------------

    async def record_downstream_call(
        self,
        service: str,
        status_code: int | None,
        outcome: str,
        duration_ms: float | None = None,
    ) -> None:
        """Registra una llamada a un servicio downstream (Extractor/Persistence)."""
        key = f"{service}:{outcome}"
        async with self._lock:
            self._downstream_calls_total[key] += 1
            if outcome == "error":
                self._downstream_errors_total[service] += 1
            if duration_ms is not None:
                hist = self._downstream_latency.get(service)
                if hist is None:
                    hist = _Histogram(_LATENCY_BUCKETS_MS)
                    self._downstream_latency[service] = hist
                hist.observe(duration_ms)

    async def record_downstream_retry(self, service: str) -> None:
        """Registra un reintento a un servicio downstream."""
        async with self._lock:
            self._downstream_retries_total[service] += 1

    # ------------------------------------------------------------------
    # Snapshot para el endpoint /metrics
    # ------------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        """Devuelve una instantánea de todas las métricas."""
        async with self._lock:
            uptime = time.monotonic() - self._start_time
            downstream_calls = {}
            for key, value in self._downstream_calls_total.items():
                service, outcome = key.split(":", 1)
                downstream_calls.setdefault(service, {})[outcome] = value

            downstream_latency = {}
            for service, hist in self._downstream_latency.items():
                downstream_latency[service] = hist.snapshot()

            return {
                "service": "orchestrator",
                "uptime_seconds": round(uptime, 3),
                "status": "running",
                "active_requests": self._active_requests,
                "requests_total": self._requests_total,
                "requests_by_status": dict(self._requests_by_status),
                "requests_by_method": dict(self._requests_by_method),
                "requests_by_endpoint": dict(self._requests_by_endpoint),
                "request_latency_ms": self._request_latency.snapshot(),
                "errors_total": self._errors_total,
                "errors_by_code": dict(self._errors_by_code),
                "errors_by_service": dict(self._errors_by_service),
                "downstream_calls": downstream_calls,
                "downstream_errors": dict(self._downstream_errors_total),
                "downstream_retries_total": dict(self._downstream_retries_total),
                "downstream_latency_ms": downstream_latency,
            }


# Única instancia compartida del recopilador de métricas.
metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Devuelve la instancia compartida de MetricsCollector."""
    return metrics_collector
