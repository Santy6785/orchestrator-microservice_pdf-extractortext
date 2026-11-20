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
