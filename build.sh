#!/usr/bin/env bash
set -euo pipefail

# Sync dependencies (including dev tools: ruff, pytest)
echo "Syncing dependencies..."
uv sync --extra dev --frozen

# Lint
echo "Running lint..."
uv run ruff check .

# Tests (exclude live multi-service system E2E tests)
echo "Running tests..."
uv run --extra dev pytest -q -m "not system"

# Build Docker image if previous steps succeeded
echo "Building Docker image..."
docker build -t orchestrator:latest .
