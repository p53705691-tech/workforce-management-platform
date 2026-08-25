"""Shared pytest fixtures.

Tests always run against ``TestingConfig`` / ``TEST_DATABASE_URL`` so the
development database is never touched by the test suite.
"""

import pathlib

import pytest
from flask import g
from flask_migrate import upgrade as alembic_upgrade

from app import create_app
from app.auth.decorators import role_required
from app.extensions import db as _db

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = str(BASE_DIR / "migrations")


@pytest.fixture(scope="session")
def app():
    """Build the Flask application once for the whole test session."""
    application = create_app("testing")

    # Test-only route for exercising `role_required` end-to-end (no real
    # M1 route needs a role restriction yet). Must be registered here,
    # before the app handles its first request — Flask forbids adding
    # routes afterwards, and the app fixture is session-scoped.
    @application.route("/__test/admin-only")
    @role_required("admin")
    def _test_admin_only():
        return "ok", 200

    with application.app_context():
        yield application


@pytest.fixture(scope="session", autouse=True)
def _migrated_database(app):
    """Bring the test database schema to head once per test session."""
    alembic_upgrade(directory=MIGRATIONS_DIR)
    yield


@pytest.fixture
def db_session(app):
    """Wrap each test in a transaction that is rolled back afterwards.

    This keeps tests isolated from each other without needing to
    recreate the schema between tests.

    Flask-SQLAlchemy's ``Session.get_bind()`` always resolves the engine
    to use via ``db.engines[<bind key>]`` and never consults
    ``Session.bind``/``Session.configure(bind=...)`` when a default
    (``None``-keyed) engine is registered, which it always is here. That
    means application code calling ``db.session.commit()`` (e.g. login
    lockout bookkeeping) would otherwise commit for real against a
    connection checked out fresh from the engine's pool, bypassing this
    fixture's rollback entirely. Temporarily substituting the registered
    engine with our own already-open, transactional ``connection`` routes
    every ORM operation through it instead, so ``join_transaction_mode``
    can turn each ``commit()`` into a savepoint release rather than a
    real commit.
    """
    connection = _db.engine.connect()
    transaction = connection.begin()

    app_engines = _db._app_engines[app]
    original_engine = app_engines[None]
    app_engines[None] = connection

    _db.session.configure(bind=connection, join_transaction_mode="create_savepoint")

    yield _db.session

    _db.session.remove()
    app_engines[None] = original_engine
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(app):
    """A test client with a clean ``flask.g`` for every test.

    The ``app`` fixture keeps a single app context pushed for the whole
    session, and Flask only pushes a fresh one per request when none is
    already active for the same app (see ``RequestContext.push``) — so
    here it never does. That means ``flask.g`` (app-context scoped) would
    otherwise carry state between tests, most importantly Flask-Login's
    cached ``current_user`` (``g._login_user``), making one test's login
    leak into the next "fresh" client as already-authenticated.
    """
    g.__dict__.clear()
    return app.test_client()
