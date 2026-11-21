import pytest
from pydantic_core import ValidationError

from app.core.config import Settings


class TestSettings:
    def test_carga_correcta_con_ambas_variables(self, monkeypatch):
        monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
        monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
        settings = Settings()
        assert settings.extractor_service_url == "http://extractor"
        assert settings.persistence_service_url == "http://persistence:8000"
        assert settings.log_level == "INFO"

    def test_falla_sin_extractor_service_url(self, monkeypatch):
        monkeypatch.delenv("EXTRACTOR_SERVICE_URL", raising=False)
        monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
        with pytest.raises(ValidationError) as exc:
            Settings()
        assert "extractor_service_url" in str(exc.value)

    def test_falla_sin_persistence_service_url(self, monkeypatch):
        monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
        monkeypatch.delenv("PERSISTENCE_SERVICE_URL", raising=False)
        with pytest.raises(ValidationError) as exc:
            Settings()
        assert "persistence_service_url" in str(exc.value)

    def test_falla_sin_ambas_variables(self, monkeypatch):
        monkeypatch.delenv("EXTRACTOR_SERVICE_URL", raising=False)
        monkeypatch.delenv("PERSISTENCE_SERVICE_URL", raising=False)
        with pytest.raises(ValidationError):
            Settings()

    def test_no_valor_por_defecto_localhost(self, monkeypatch):
        monkeypatch.delenv("EXTRACTOR_SERVICE_URL", raising=False)
        monkeypatch.delenv("PERSISTENCE_SERVICE_URL", raising=False)
        with pytest.raises(ValidationError):
            Settings()


class TestSettingsTimeouts:
    def test_timeouts_defaults(self, monkeypatch):
        monkeypatch.delenv("EXTRACTOR_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("PERSISTENCE_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("HEALTH_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
        monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
        s = Settings()
        assert s.extractor_timeout_seconds == 30.0
        assert s.persistence_timeout_seconds == 5.0
        assert s.health_timeout_seconds == 2.0

    def test_timeouts_desde_variables_de_entorno(self, monkeypatch):
        monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
        monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
        monkeypatch.setenv("EXTRACTOR_TIMEOUT_SECONDS", "45.5")
        monkeypatch.setenv("PERSISTENCE_TIMEOUT_SECONDS", "7.0")
        monkeypatch.setenv("HEALTH_TIMEOUT_SECONDS", "2.5")
        s = Settings()
        assert s.extractor_timeout_seconds == 45.5
        assert s.persistence_timeout_seconds == 7.0
        assert s.health_timeout_seconds == 2.5

    @pytest.mark.parametrize("valor", ["0", "-1", "abc", "not-a-number"])
    def test_timeout_invalido_falla_al_arrancar_nombrando_variable(
        self, monkeypatch, valor
    ):
        monkeypatch.setenv("EXTRACTOR_SERVICE_URL", "http://extractor")
        monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence:8000")
        monkeypatch.setenv("EXTRACTOR_TIMEOUT_SECONDS", valor)
        with pytest.raises(ValidationError) as exc:
            Settings()
        assert "extractor_timeout_seconds" in str(exc.value)
