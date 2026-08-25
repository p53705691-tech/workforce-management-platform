"""Application configuration.

Configuration values are read from environment variables. No secret
literals live in this module; ``ProductionConfig`` fails fast if required
secrets are missing so the application never starts in an insecure state.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    """Defaults shared by every environment."""

    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEBUG = False
    TESTING = False

    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Round B decision: an absolute expiry for the signed session cookie,
    # independent of activity. Without this, Flask's default is "no
    # expiry beyond the browser session" for a non-permanent session, but
    # this app marks the session permanent at login (see
    # app.routes.auth.login) specifically so a stolen or forgotten-open
    # cookie cannot be replayed forever — it stops working 12 hours after
    # login regardless of use. 12 hours comfortably covers a single work
    # shift (including a reasonable amount of overtime) without requiring
    # an active user to re-authenticate mid-shift.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # This is a form-based app with no file uploads, so 1 MB is generous
    # for any legitimate request body. Without this, Flask has no upper
    # bound on request body size and the already-registered 413 handler
    # in app.errors is unreachable.
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    WTF_CSRF_ENABLED = False


class ProductionConfig(BaseConfig):
    """Production configuration.

    Fails fast at instantiation time if required secrets are not
    configured in the environment, so the app can never boot into
    production with a missing SECRET_KEY or DATABASE_URL.
    """

    DEBUG = False

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    def __init__(self):
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError(
                "SECRET_KEY environment variable must be set in production."
            )
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL environment variable must be set in production."
            )


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
