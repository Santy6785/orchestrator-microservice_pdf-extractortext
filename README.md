# Orquestador Microservice

> FastAPI orchestrator for the PDF‑Extractor system.

## Overview

This microservice receives PDF documents, forwards them to the **Extractor** service, and coordinates persistence via the **Persistence** service.  It provides a thin HTTP API that is stateless and relies on environment‑variable service discovery.

Key features:
- FastAPI with async request‑ID propagation and pause handling middleware.
- Clean contract‑first design (see `docs/contratos/`).
- Comprehensive test suite (unit & integration).
- Multi‑stage Docker build using **uv**.
- Simple `build.sh` script that lints, runs tests, and builds the Docker image.

## Repository layout

```
orchestrator-microservice_pdf-extractortext/
├─ app/                     # FastAPI application code
│   ├─ api/v1/              # Routers (documents, control)
│   ├─ core/                # Config, logging, middleware
│   ├─ dependencies.py       # DI helpers
│   └─ main.py               # Application factory
├─ docs/contratos/          # OpenAPI contract files (markdown)
├─ tests/                   # Pytest suite
├─ Dockerfile               # Multi‑stage build
├─ docker-compose.yml       # Service definition for local dev
├─ build.sh                 # Lint → test → Docker build
├─ .gitignore               # Standard ignore patterns
└─ README.md                # <‑‑ this file
```

## Getting started (local)

```bash
# Clone the repo and cd into the microservice
git clone <repo-url>
cd orchestrator-microservice_pdf-extractortext

# Create a virtual environment (optional) – the project uses uv
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate

# Install dependencies via uv (includes dev deps)
uv sync --frozen

# Run the API (development server)
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

## API reference

### Document endpoints (`/api/v1/documents`)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/upload` | Upload a PDF file; returns the persisted document with `id`, `checksum`, `extracted_text`, `created_at`, `filename`, `page_count` and `file_size_bytes` (HTTP 200). |
| `GET`  | `/{document_id}` | Obtiene un documento por su ID (HTTP 200). |

### Control endpoints (`/api/v1/control`)
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `"healthy"` when the orchestrator can reach downstream services. |
| `POST`| `/shutdown` | Gracefully stop the service. |
| `POST`| `/pause` | Pause processing of new requests (middleware respects this flag). |
| `POST`| `/resume` | Resume processing after a pause. |
| `GET` | `/metrics` | Placeholder for future Prometheus metrics. |

Full OpenAPI docs are available at `http://localhost:8000/docs`.

## Testing

```bash
# Run the entire test suite (including integration tests)
uv run --extra dev pytest -q -m "not system"
```

All tests should pass (`129 passed`).

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
