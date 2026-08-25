"""Flask extension singletons.

These are created once at import time but not bound to an application
here. They are wired up to a concrete Flask app inside the
``create_app`` factory in ``app/__init__.py``.
"""

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
