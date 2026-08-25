import pytest

from app import create_app
from app.config import DevelopmentConfig, ProductionConfig, TestingConfig

pytestmark = pytest.mark.unit


def test_create_app_builds_successfully():
    application = create_app("testing")
    assert application is not None
    assert application.config["TESTING"] is True


def test_create_app_raises_for_unrecognized_config_name():
    with pytest.raises(RuntimeError):
        create_app("bogus")


def test_development_config_has_debug_enabled():
    assert DevelopmentConfig.DEBUG is True


def test_testing_config_has_debug_and_testing_enabled():
    assert TestingConfig.DEBUG is True
    assert TestingConfig.TESTING is True


def test_production_config_has_debug_disabled():
    assert ProductionConfig.DEBUG is False


def test_production_config_raises_without_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")

    with pytest.raises(RuntimeError):
        ProductionConfig()


def test_production_config_raises_without_database_url(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError):
        ProductionConfig()


def test_production_config_succeeds_with_required_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")

    config = ProductionConfig()
    assert config.SESSION_COOKIE_SECURE is True
    assert config.SESSION_COOKIE_HTTPONLY is True
    assert config.SESSION_COOKIE_SAMESITE == "Lax"
