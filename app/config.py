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

    # Without this, Flask's default (True) re-signs the session cookie
    # with a fresh expiry timestamp on every response for a permanent
    # session, turning the "absolute" 12-hour expiry above into a
    # 12-hour *idle* timeout instead — an actively-used (or
    # periodically-polled) stolen cookie would then never actually
    # expire, defeating the whole point of PERMANENT_SESSION_LIFETIME
    # (security-review finding). False makes the expiry timestamp fixed
    # at login and never extended.
    SESSION_REFRESH_EACH_REQUEST = False

    # This is a form-based app with no file uploads, so 1 MB is generous
    # for any legitimate request body. Without this, Flask has no upper
    # bound on request body size and the already-registered 413 handler
    # in app.errors is unreachable.
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    # Whether this process sits behind a trusted reverse proxy (Nginx,
    # per CLAUDE.md's production stack) that sets X-Forwarded-For/-Proto.
    # False everywhere except ProductionConfig: trusting these headers
    # from a client that connects directly (no proxy in front) lets that
    # client spoof its own source IP, defeating both per-IP rate
    # limiting (app.extensions.limiter) and the audit log's IP column
    # (app.services.audit.record) — see wsgi.py for where this is
    # actually applied.
    TRUST_PROXY = False

    # Flask-Limiter's storage backend. In-memory (the Limiter default,
    # left unset here) is per-process — with more than one Gunicorn
    # worker, each worker enforces its own independent counter, so a
    # "10 per minute" limit effectively becomes "10 per minute per
    # worker" (security-review finding). A shared backend makes limits
    # correct across every worker; only required in ProductionConfig,
    # below — development/testing keep the simpler in-memory default.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI")

    # SMTP configuration for app.services.notifications.send_email — read
    # entirely from the environment, never hardcoded here, so no secret
    # literal (a password in particular) ever lives in source control.
    # Only consulted when MAIL_BACKEND is "smtp" (see that module's
    # docstring); every other backend ignores these entirely.
    SMTP_HOST = os.environ.get("SMTP_HOST")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    # Defaults to requiring STARTTLS: sending real mail in plaintext
    # should never be the silent default. Set SMTP_USE_TLS=false
    # explicitly to opt out (e.g. a local/dev-only relay that doesn't
    # support it).
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").strip().lower() not in (
        "false",
        "0",
        "",
    )
    MAIL_FROM_ADDRESS = os.environ.get("MAIL_FROM_ADDRESS")


class DevelopmentConfig(BaseConfig):
    DEBUG = True

    # No SMTP server is expected to exist in local development — emails
    # are logged instead of sent, so the notification call sites (leave
    # requests, account creation, ...) can be exercised without any
    # extra setup.
    MAIL_BACKEND = "console"


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    WTF_CSRF_ENABLED = False
    # The test suite logs in far more than any real rate limit would
    # allow within its run time (many tests share one session-scoped app
    # — see tests/conftest.py), so per-IP login throttling would produce
    # spurious failures unrelated to what each test actually checks.
    RATELIMIT_ENABLED = False

    # The suite must never attempt real network I/O for an email send.
    # A test that wants to assert on actual email content/recipient
    # overrides this on the app fixture's config for the duration of
    # that test (see tests/integration/test_notifications.py).
    MAIL_BACKEND = "suppress"


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

    # Real email delivery is required in production — silently falling
    # back to "console" (just logging) would mean leave-request/account
    # notifications quietly never reach anyone.
    MAIL_BACKEND = "smtp"

    # Production is the one environment actually deployed behind Nginx
    # (CLAUDE.md's production stack) — see wsgi.py for what this enables.
    TRUST_PROXY = True

    def __init__(self):
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError(
                "SECRET_KEY environment variable must be set in production."
            )
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL environment variable must be set in production."
            )
        # MAIL_BACKEND is "smtp" in production (above), so these two are
        # the minimum needed for app.services.notifications.send_email to
        # actually deliver anything — same fail-fast precedent as
        # SECRET_KEY/DATABASE_URL just above, rather than booting
        # successfully and only discovering the gap the first time a
        # leave request or account-creation email silently fails to
        # send.
        if not os.environ.get("SMTP_HOST"):
            raise RuntimeError(
                "SMTP_HOST environment variable must be set in production."
            )
        if not os.environ.get("MAIL_FROM_ADDRESS"):
            raise RuntimeError(
                "MAIL_FROM_ADDRESS environment variable must be set in production."
            )
        # Without a shared rate-limit storage backend, per-IP throttling
        # (login, forgot-password) silently becomes per-worker instead of
        # global the moment Gunicorn runs more than one worker — see
        # BaseConfig.RATELIMIT_STORAGE_URI and app.extensions.limiter.
        if not os.environ.get("RATELIMIT_STORAGE_URI"):
            raise RuntimeError(
                "RATELIMIT_STORAGE_URI environment variable must be set in "
                "production (e.g. a Redis URL) — the default in-memory rate "
                "limit storage is per-process and not safe with more than "
                "one Gunicorn worker."
            )


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
