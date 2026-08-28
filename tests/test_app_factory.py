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


def test_production_config_raises_without_smtp_host(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("MAIL_FROM_ADDRESS", "noreply@example.com")

    with pytest.raises(RuntimeError):
        ProductionConfig()


def test_production_config_raises_without_mail_from_address(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("MAIL_FROM_ADDRESS", raising=False)

    with pytest.raises(RuntimeError):
        ProductionConfig()


def test_production_config_raises_without_ratelimit_storage_uri(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MAIL_FROM_ADDRESS", "noreply@example.com")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)

    with pytest.raises(RuntimeError):
        ProductionConfig()


def test_production_config_succeeds_with_required_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    # app.services.notifications.send_email requires these two in
    # production (MAIL_BACKEND is "smtp" there) — same fail-fast
    # precedent as SECRET_KEY/DATABASE_URL above, so a production
    # config also needs them to construct successfully.
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MAIL_FROM_ADDRESS", "noreply@example.com")
    # app.extensions.limiter requires a shared storage backend in
    # production — same fail-fast precedent as the vars above.
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/0")

    config = ProductionConfig()
    assert config.SESSION_COOKIE_SECURE is True
    assert config.SESSION_COOKIE_HTTPONLY is True
    assert config.SESSION_COOKIE_SAMESITE == "Lax"
    assert config.MAIL_BACKEND == "smtp"
    assert config.TRUST_PROXY is True
