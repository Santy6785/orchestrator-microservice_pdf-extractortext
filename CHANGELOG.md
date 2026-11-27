# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-10-19
### Added
- Multi‑stage Dockerfile for building the orchestrator microservice.
- `docker-compose.yml` and `build.sh` for local development and CI.
- `.gitignore` covering typical Python, virtualenv, and Docker artefacts.
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) that lints, tests, and builds the Docker image.
- Comprehensive README with overview, setup, Docker usage, API reference, and contribution guidelines.
- Alias endpoints (`/documents` and `/api/v1/documents/`) to satisfy router test.
- Updated test dependency overrides to use function objects.
- All tests now pass (`12 passed`).

### Fixed
- Dependency override issue in `tests/test_documents.py`.
- Router test failure by adding minimal `/documents` alias route.

### Changed
- Refactored `app/main.py` to include the alias route and improved documentation comments.

## [Unreleased]

### Added
- Health checks con distinción liveness (`/api/v1/control/health/live`) y readiness (`/api/v1/control/health/ready`).
- Endpoint `/api/v1/control/trace` con metadata de request/response redactada (sin PDF, texto extraído, secretos).
- Endpoint `/api/v1/control/metrics` con métricas operativas reales (HTTP, errores, latencias, retries, dependencias).
- Logging estructurado JSON a stdout/stderr con redacción de datos sensibles y request-id propagado.
- Máquina de estados de ciclo de vida (RUNNING/PAUSED/SHUTTING_DOWN/STOPPED) con transiciones válidas y locks contra race conditions.
- Protección de endpoints de control internos mediante `internal_access_middleware` (loopback o `X-Internal-Token`).
- Variable de entorno `INTERNAL_CONTROL_TOKEN` para restringir acceso a endpoints internos.
- Documentación consolidada en `docs/observabilidad.md` y contratos actualizados en `docs/contratos/`.

### Changed
- `GET /api/v1/control/health` es ahora alias de `/health/ready` (mantiene compatibilidad con Docker y Traefik).
- Endpoints de control (`/pause`, `/resume`, `/shutdown`, `/metrics`, `/trace`) no están expuestos públicamente por Traefik.
- `README.md` actualizado con rutas reales, conteo de tests y sección de observabilidad.
- `docs/conectividad.md` actualizado con puertos reales y tabla de endpoints públicos vs internos.
- `docs/contratos/get-metrics.md`, `post-pause.md`, `post-resume.md`, `post-shutdown.md` actualizados a la implementación efectiva.
- `.env.example` incluye `INTERNAL_CONTROL_TOKEN`.

### Fixed
- Orden de middlewares para que `request_id` esté disponible antes de trace, metrics y access logging.
- Circular import entre `app/core/middleware.py` y `app/core/trace.py`/`app/core/logging.py`.
- Lint (ruff) limpio en todos los archivos modificados.
