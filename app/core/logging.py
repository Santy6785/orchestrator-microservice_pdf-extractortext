import logging
import os

def configure_logging():
    """Configure root logger based on LOG_LEVEL env var.
    Logs are emitted in a simple format suitable for container stdout.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # Reduce noisy logs from third‑party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(level)
