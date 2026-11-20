from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación cargada desde variables de entorno.

    Variables obligatorias:
        EXTRACTOR_SERVICE_URL  URL base del microservicio Extractor.
        PERSISTENCE_SERVICE_URL URL base del microservicio de Persistencia.

    Si falta alguna variable obligatoria, Pydantic lanza ValidationError
    al instanciar Settings, haciendo fallar el arranque con un mensaje que
    identifica claramente la variable faltante.

    Variables opcionales:
        LOG_LEVEL              Nivel de logging (default: INFO).
    """

    extractor_service_url: str
    persistence_service_url: str
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


# Única instancia compartida de la configuración.
settings = Settings()
