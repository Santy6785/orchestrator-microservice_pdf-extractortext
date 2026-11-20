import os

# Variables de entorno obligatorias para que la app (y Settings) pueda importarse
# en los tests. O-03 las declara obligatorias; conftest las provee para el suite.
os.environ.setdefault("EXTRACTOR_SERVICE_URL", "http://extractor")
os.environ.setdefault("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
os.environ.setdefault("LOG_LEVEL", "INFO")
