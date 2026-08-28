"""Flask extension singletons.

These are created once at import time but not bound to an application
here. They are wired up to a concrete Flask app inside the
``create_app`` factory in ``app/__init__.py``.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
# Per-IP only (see app.routes.auth.login for the actual limits applied):
# does not stop a distributed attack from many IPs, but raises the cost
# of both the Argon2/CPU exhaustion and unbounded audit-row-insertion
# issues a single unauthenticated attacker could otherwise cause on this
# endpoint (security-review finding). Storage defaults to in-memory
# (per-process, not shared across Gunicorn workers) unless
# RATELIMIT_STORAGE_URI is set (app.config.BaseConfig) — Flask-Limiter
# reads that config key automatically in init_app below. ProductionConfig
# fails fast if it's unset, so production always runs with a shared
# backend (e.g. Redis) once more than one worker is in play. Per-IP
# accuracy behind a reverse proxy additionally depends on ProxyFix being
# applied — see wsgi.py.
limiter = Limiter(key_func=get_remote_address)
