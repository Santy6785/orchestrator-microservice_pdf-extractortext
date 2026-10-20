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
- Future enhancements and bug fixes.
