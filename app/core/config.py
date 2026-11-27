from pydantic import Field, model_validator
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
        LOG_LEVEL                  Nivel de logging (default: INFO).
        EXTRACTOR_TIMEOUT_SECONDS  Timeout del cliente Extractor, en segundos
                                   (default: 30.0).
        PERSISTENCE_TIMEOUT_SECONDS Timeout del cliente Persistencia, en
                                    segundos (default: 5.0).
        HEALTH_TIMEOUT_SECONDS     Timeout de los clientes usados por
                                   /control/health, en segundos (default: 2.0).

    Los timeouts deben ser mayores que 0; un valor inválido hace fallar el
    arranque con un mensaje que nombra la variable.
    """

    extractor_service_url: str
    persistence_service_url: str
    log_level: str = "INFO"
    extractor_timeout_seconds: float = Field(30.0, gt=0)
    persistence_timeout_seconds: float = Field(5.0, gt=0)
    health_timeout_seconds: float = Field(2.0, gt=0)
    environment: str = Field(
        "development",
        description="Entorno de ejecución: development, staging o production",
    )
    internal_control_token: str | None = Field(
        None, description="Token opcional para acceso a endpoints de control internos"
    )

    @model_validator(mode="after")
    def _require_internal_token_in_production(self) -> "Settings":
        """Exige INTERNAL_CONTROL_TOKEN cuando el entorno es production."""
        if self.environment == "production" and not self.internal_control_token:
            raise ValueError(
                "INTERNAL_CONTROL_TOKEN es obligatorio cuando ENVIRONMENT=production. "
                "Configure un token para proteger los endpoints de control internos "
                "(/pause, /resume, /shutdown, /metrics, /trace)."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


# Única instancia compartida de la configuración.
settings = Settings()
