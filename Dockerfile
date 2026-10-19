# Use the official Python image as a base
FROM python:3.12-slim AS builder

# Install uv (the modern Python package manager)
RUN pip install --no-cache-dir uv

# Set workdir
WORKDIR /app

# Copy pyproject and lock files
COPY pyproject.toml uv.lock ./

# Install dependencies (including dev for linting & testing) in a virtual env
RUN uv sync --no-dev --frozen && \
    # Remove build-time caches
    rm -rf /root/.cache

# Copy source code
COPY . .

# Runtime image
FROM python:3.12-slim AS runtime
WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /root/.local /root/.local
ENV PATH="/root/.local/bin:$PATH"

# Copy only needed files
COPY --from=builder /app /app

# Expose the port FastAPI runs on
EXPOSE 8000

# Command to run the service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
