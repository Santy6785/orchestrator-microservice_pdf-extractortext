import logging
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    extractor_service_url: str = os.getenv("EXTRACTOR_SERVICE_URL", "http://localhost:8001")
    persistence_service_url: str = os.getenv("PERSISTENCE_SERVICE_URL", "http://localhost:8002")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", env_file_encoding="utf-8")

settings = Settings()
