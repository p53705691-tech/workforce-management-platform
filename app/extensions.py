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
# endpoint (security-review finding). Storage defaults to in-memory,
# which is per-process, not shared across gunicorn workers — acceptable
# for a small worker count, but a real limitation worth knowing before
# scaling up; set RATELIMIT_STORAGE_URI to a shared backend (e.g. Redis)
# if that gap ever matters more than the added infrastructure it needs.
limiter = Limiter(key_func=get_remote_address)
