"""Application factory."""

import os
from pathlib import Path

from flask import Flask, jsonify

from app.config import CONFIG_BY_NAME
from app.errors import register_error_handlers
from app.extensions import csrf, db, login_manager, migrate

# Importing app.models registers every model with db.metadata, so Alembic
# autogeneration and ORM usage can discover them regardless of which
# routes/entrypoints get imported first.
from app import models  # noqa: F401

# Per project-structure.md, templates/ and static/ live at the repository
# root, not inside the app/ package — Flask's default (relative to
# app.root_path) would look inside app/ instead, so both are pointed at
# their real location explicitly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(config_name=None):
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )

    # An unset FLASK_ENV defaults to development for local-dev ergonomics,
    # but an unrecognized value is a real misconfiguration (e.g. a typo
    # that would otherwise silently fail open into DevelopmentConfig, with
    # DEBUG=True and no HTTPS/HSTS enforcement) and must not be papered
    # over.
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    try:
        config_class = CONFIG_BY_NAME[config_name]
    except KeyError as exc:
        raise RuntimeError(
            f"Unrecognized config_name {config_name!r}. Expected one of: "
            f"{', '.join(sorted(CONFIG_BY_NAME))}."
        ) from exc
    app.config.from_object(config_class())

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "error"
    csrf.init_app(app)

    register_error_handlers(app)

    @app.template_filter("local_dt")
    def local_dt(value, tz):
        """Render an aware datetime in an explicit display timezone.

        Never render a raw datetime directly in a template: its tzinfo on
        read-back reflects whatever timezone the database session happens
        to be in, not any timezone the application actually chose. This
        filter makes the display timezone explicit and consistent
        regardless of server/session configuration, per the project's
        time-and-money rule that storage/application/display timezones
        must each be deliberate, not ambient.
        """
        if value is None:
            return ""
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")

    @app.after_request
    def set_security_headers(response):
        """Add baseline hardening headers to every response.

        ``Strict-Transport-Security`` is only added when
        ``SESSION_COOKIE_SECURE`` is true (i.e. the app is actually being
        served over HTTPS, per ``ProductionConfig``) — sending HSTS on a
        plain-HTTP development server would tell browsers to force HTTPS
        for a host that doesn't serve it, actively breaking local
        development rather than hardening anything.
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # The app serves no inline scripts and only one static JS file
        # (per-origin, same-site), so a strict policy costs nothing
        # today: no external scripts/styles/frames, no embedding, no
        # cross-origin form submission, no plugin content.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'; object-src 'none'",
        )
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    from app.routes.attendance import attendance_bp
    from app.routes.audit import audit_bp
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.departments import departments_bp
    from app.routes.employees import employees_bp
    from app.routes.labor_cost import labor_cost_bp
    from app.routes.leave import leave_bp
    from app.routes.main import main_bp
    from app.routes.schedule import schedule_bp

    app.register_blueprint(attendance_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(departments_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(labor_cost_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(schedule_bp)

    from app.cli import register_cli

    register_cli(app)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok"), 200

    return app
