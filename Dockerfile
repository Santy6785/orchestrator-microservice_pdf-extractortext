# Use the official Python image as a base
FROM python:3.12-slim AS builder

# Install uv (the modern Python package manager)
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv

# Set workdir
WORKDIR /app

# Copy pyproject and lock files
COPY pyproject.toml uv.lock ./

# Install dependencies (including dev for linting & testing) in a virtual env
RUN uv sync --frozen --no-dev --no-install-project

# Copy only project files needed for install
COPY app/ ./app/
COPY README.md ./README.md

# Install the project package in the venv
RUN uv sync --frozen --no-dev --no-editable

# Runtime image
FROM python:3.12-slim AS runtime
WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Expose the port FastAPI runs on
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/control/health', timeout=8)" || exit 1

# Command to run the service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
