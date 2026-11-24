# Orquestador Microservice

> FastAPI orchestrator for the PDF‑Extractor system.

## Overview

This microservice receives PDF documents, forwards them to the **Extractor** service, and coordinates persistence via the **Persistence** service. It provides a thin HTTP API that is stateless and relies on environment‑variable service discovery.

Key features:
- FastAPI with async request‑ID propagation and pause handling middleware.
- Clean contract‑first design (see `docs/contratos/`).
- Architecture Decision Records (`docs/decisiones.md`) and connectivity guide (`docs/conectividad.md`).
- Comprehensive test suite (unit & integration).
- Multi‑stage Docker build using **uv**.
- Simple `build.sh` script that lints, runs tests, and builds the Docker image.

## Internal URLs & Ports

In the shared Docker Compose network (`${DOCKER_NETWORK_NAME:-pdf-extractortext_pdf-network}`), the orchestrator and its downstream dependencies communicate using internal container hostnames and ports:

| Service | Container / Host | Internal Port | Internal URL | External / Routing |
|---------|------------------|---------------|--------------|--------------------|
| **Orquestador** | `orchestrator` | `8000` | `http://orchestrator:8000` | `https://universidad.localhost/api` (via Traefik) |
| **Extractor** | `extractor` | `80` | `http://extractor` | Internal network only (`EXTRACTOR_SERVICE_URL`) |
| **Persistencia** | `persistence` | `8000` | `http://persistence:8000` | Internal network only (`PERSISTENCE_SERVICE_URL`) |

For local development outside Docker (e.g., running `uvicorn` on the host), configure `.env` with the corresponding host-mapped URLs and ports. See `docs/conectividad.md` for full endpoint mappings, error matrices, and timeouts.

## Repository layout