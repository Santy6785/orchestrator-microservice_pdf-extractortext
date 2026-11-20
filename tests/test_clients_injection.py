from app.clients.extractor_client import ExtractorClient
from app.clients.persistence_client import PersistenceClient
from app.core.config import settings


class TestClientesInyeccion:
    def test_extractor_client_usa_url_de_settings(self):
        assert ExtractorClient().service_url == settings.extractor_service_url

    def test_persistence_client_usa_url_de_settings(self):
        assert PersistenceClient().service_url == settings.persistence_service_url

    def test_clientes_no_tienen_urls_hardcodeadas(self):
        extractor_url = ExtractorClient().service_url
        persistence_url = PersistenceClient().service_url
        assert "localhost" not in extractor_url
        assert "localhost" not in persistence_url
        assert "mock" not in extractor_url
        assert "mock" not in persistence_url

    def test_clientes_reciben_urls_distintas(self):
        assert ExtractorClient().service_url != PersistenceClient().service_url

    def test_unica_instancia_settings_compartida(self):
        from app.core.config import settings as s1
        from app.core.config import settings as s2

        assert s1 is s2
        assert settings is s1
