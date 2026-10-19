#!/usr/bin/env bash
set -euo pipefail

# Lint
echo "Running lint..."
ruff .

# Tests
echo "Running tests..."
uv run --extra dev pytest -q

# Build Docker image if previous steps succeeded
echo "Building Docker image..."
docker build -t orchestrator .
