# Orquestador Microservice

> FastAPI orchestrator for the PDF‑Extractor system.

## Overview

This microservice receives PDF documents, forwards them to the **Extractor** service, and coordinates persistence via the **Persistence** service. It provides a thin HTTP API that is stateless and relies on environment‑variable service discovery.

Key features:

- FastAPI with async request‑ID propagation, pause handling middleware, and structured access logging.
- Clean contract‑first design (see `docs/contratos/`).
- Architecture Decision Records (`docs/decisiones.md`) and connectivity guide (`docs/conectividad.md`).
- Comprehensive test suite (unit & integration).
- Observability: structured logging, health checks (liveness/readiness), request trace, and operational metrics.
- Secure lifecycle: `/pause`, `/resume`, `/shutdown` restricted to internal access.
- Multi‑stage Docker build using **uv**.
- Simple `build.sh` script that lints, runs tests, and builds the Docker image.

## Internal URLs & Ports

In the shared Docker Compose network (`${DOCKER_NETWORK_NAME:-pdf-extractortext_pdf-network}`), the orchestrator and its downstream dependencies communicate using internal container hostnames and ports:

| Service | Container / Host | Internal Port | Internal URL | External / Routing |
|---------|------------------|---------------|--------------|--------------------|
| **Orquestador** | `orchestrator` | `8000` | `http://orchestrator:8000` | `https://universidad.localhost/api` (via Traefik) |
| **Extractor** | `extractor` | `80` | `http://extractor` | Internal network only (`EXTRACTOR_SERVICE_URL`) |
| **Persistencia** | `persistence` | `8000` | `http://persistence:8000` | Internal network only (`PERSISTENCE_SERVICE_URL`) |

For local development outside Docker (e.g., running `uvicorn` on the host), configure `.env` with the corresponding host‑mapped URLs and ports. See `docs/conectividad.md` for full endpoint mappings, error matrices, and timeouts.

## Startup Order

To ensure downstream dependencies are ready before receiving traffic, the system services must be started in the following order:

## Run the API (development server)

```bash
uvicorn app.main:app --reload
```

The service will be available at `http://127.0.0.1:8000`.

## Docker usage

### Build the image

```bash
./build.sh   # lint → test → docker build (tag: orchestrator)
```

### Run with Docker Compose

```bash
docker compose up -d   # starts the orchestrator service
```

The Compose file sets the required environment variables:

- `EXTRACTOR_SERVICE_URL` – URL of the extractor microservice (e.g. `http://mock-extractor`).
- `PERSISTENCE_SERVICE_URL` – URL of the persistence microservice.

You can test the health endpoint:

```bash
curl http://localhost:8000/api/v1/control/health
```

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `EXTRACTOR_SERVICE_URL` | Base URL for the PDF extractor service | *required* |
| `PERSISTENCE_SERVICE_URL` | Base URL for the persistence service | *required* |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `EXTRACTOR_TIMEOUT_SECONDS` | Timeout del cliente Extractor, en segundos | `30.0` |
| `PERSISTENCE_TIMEOUT_SECONDS` | Timeout del cliente Persistencia, en segundos | `5.0` |
| `HEALTH_TIMEOUT_SECONDS` | Timeout de los clientes usados por `/control/health`, en segundos | `2.0` |
| `ENVIRONMENT` | Entorno de ejecución (`development`, `staging`, `production`). En `production` se exige `INTERNAL_CONTROL_TOKEN`. | `development` |
| `INTERNAL_CONTROL_TOKEN` | Token para proteger endpoints de control internos (`/pause`, `/resume`, `/shutdown`, `/metrics`, `/trace`). Si no se configura, solo se permite acceso desde hosts internos (loopback). Obligatorio en `production`. | *none* |

## API reference

### Document endpoints (`/api/v1/documents`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/upload` | Upload a PDF file; returns the persisted document with `id`, `checksum`, `extracted_text`, `created_at`, `filename`, `page_count` and `file_size_bytes` (HTTP 200). |
| `GET` | `/{document_id}` | Obtiene un documento por su ID (HTTP 200). |
| `GET` | `/{document_id}/download` | Descarga el texto extraído como archivo Markdown (HTTP 200). |
| `DELETE` | `/{document_id}` | Elimina un documento por su ID (HTTP 204 No Content). |

### Control endpoints (`/api/v1/control`)

| Method | Path | Description | Access |
|--------|------|-------------|--------|
| `GET` | `/health/live` | Liveness: verifica que el proceso del Orchestrator responde. No llama a dependencias. | Público |
| `GET` | `/health/ready` | Readiness: verifica el Orchestrator y sus dependencias (Extractor, Persistencia). | Público |
| `GET` | `/health` | Alias de `/health/ready`. Usado por Docker y Traefik healthchecks. | Público |
| `GET` | `/trace` | Devuelve la última entrada de trace (request/response metadata, sin datos sensibles). | Interno |
| `GET` | `/metrics` | Métricas operativas (requests, errores, latencias, retries, dependencias). | Interno |
| `POST` | `/pause` | Pausa el servicio (503 para nuevas peticiones no-control). | Interno |
| `POST` | `/resume` | Reanuda el servicio tras una pausa. | Interno |
| `POST` | `/shutdown` | Apagado seguro con drenado de peticiones activas y SIGTERM. | Interno |

> **Endpoints internos:** `/trace`, `/metrics`, `/pause`, `/resume` y `/shutdown` no están expuestos públicamente a través de Traefik. Solo son accesibles desde hosts internos (loopback) o presentando el header `X-Internal-Token` con el valor configurado en `INTERNAL_CONTROL_TOKEN`.
>
> **Nota en Docker:** la IP que ve el orquestador es la del cliente directo (otro contenedor o el gateway), no la del usuario final. En una red compartida de Docker, cualquier contenedor puede alcanzar estos endpoints si no hay `INTERNAL_CONTROL_TOKEN` configurado. En despliegues productivos, configura el token y ejecuta con `ENVIRONMENT=production` (la app fallará al arrancar si falta el token en ese entorno).

Full OpenAPI docs are available at `http://localhost:8000/docs`.

## Observability

### Structured logging

Logs emitense como JSON de una línea a `stdout` (todos los niveles) y `stderr` (WARNING y superior). Cada registro incluye `timestamp`, `level`, `service`, `request_id` y `message`. Los headers `Authorization`, cookies, contenido PDF (`%PDF-`) y rutas de usuario se redactan automáticamente.

### Health checks

- **Liveness** (`GET /api/v1/control/health/live`): devuelve `{"orchestrator": "alive"}` sin llamar a dependencias. Siempre HTTP 200 si el proceso responde.
- **Readiness** (`GET /api/v1/control/health/ready`): verifica Extractor (`GET /health`, espera `{"status": "ok"}`) y Persistencia (`GET /health/ready`, espera `{"status": "ready"}`). Devuelve HTTP 200 si ambas están sanas, HTTP 503 si al menos una falla. Cada dependencia tiene timeout individual (`HEALTH_TIMEOUT_SECONDS`, default 2s) y el chequeo completo tiene timeout global (5s).
- **Health compuesto** (`GET /api/v1/control/health`): alias de readiness, usado por Docker y Traefik.

### Trace

`GET /api/v1/control/trace` devuelve la última entrada de request/response registrada: `request_id`, `method`, `path`, `status_code`, `response_size_bytes`, `duration_ms`, `timestamp`, cabeceras sanitizadas (sin `Authorization`, cookies, etc.) y query params (sin claves sensibles). Nunca almacena cuerpos de PDF, texto extraído, tokens ni secretos. Retención: últimas 100 entradas por instancia.

### Metrics

`GET /api/v1/control/metrics` expone: `uptime_seconds`, `status`, `active_requests`, `requests_total`, `requests_by_status`, `requests_by_method`, `requests_by_endpoint`, `request_latency_ms` (histograma), `errors_total`, `errors_by_code`, `errors_by_service`, `downstream_calls`, `downstream_errors`, `downstream_retries_total` y `downstream_latency_ms`. Las etiquetas son de baja cardinalidad (no hay `request_id`, `document_id` ni paths completos).

## Testing

```bash
# Run the entire test suite (including integration tests)
uv run --extra dev pytest -q -m "not system"
```

All tests pass.

## Build script (`build.sh`)

The script performs three steps:

1. **Lint** – `ruff .`
2. **Test** – `uv run --extra dev pytest -q -m "not system"`
3. **Docker build** – `docker build -t orchestrator .`

It aborts on the first failure, ensuring that only clean, tested code is containerized.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Write tests for any new behavior.
4. Run `./build.sh` locally; ensure it exits with status 0.
5. Open a Pull Request.

## License

MIT License – see `LICENSE` file.

```text
persistencia → extractor → orquestador → front
```
