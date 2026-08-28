"""Fixtures for tests that need true, multi-connection concurrency.

See ``tests/integration/test_concurrency.py``'s module docstring for the
full rationale. In short: ``tests/conftest.py``'s ``db_session`` fixture
wraps every test in one already-open transaction (plus a SAVEPOINT) that
is rolled back at teardown — every ORM operation in a test using it goes
through that single connection, so it can prove a *later* insert within
the same transaction conflicts with an earlier uncommitted one, but it
can never demonstrate that a database constraint actually stops a race
between two independent, separately-committing transactions. This module
provides that instead, for the handful of tests that specifically need
it.
"""

import pytest
from sqlalchemy.orm import Session

from app.extensions import db as _db


@pytest.fixture
def concurrent_db_sessions(app):
    """Two independent SQLAlchemy sessions, each able to commit for real.

    Both check out their own connection from the same engine the app is
    already configured to use under the ``testing`` config
    (``TEST_DATABASE_URL``) — the actual prerequisite for a genuine
    cross-transaction race: two separate, independently committing
    database transactions, not two inserts sharing one already-open
    transaction the way ``tests/conftest.py``'s ``db_session`` fixture
    works.

    Neither session is routed through ``db_session``'s savepoint-rollback
    isolation, so any row a test creates through these sessions is real
    and permanent. Tests using this fixture are responsible for deleting
    their own rows (see ``_cleanup_organization`` in
    ``test_concurrency.py``) — there is no automatic rollback to rely on.
    """
    engine = _db.engine
    session_a = Session(bind=engine)
    session_b = Session(bind=engine)
    try:
        yield session_a, session_b
    finally:
        session_a.rollback()
        session_b.rollback()
        session_a.close()
        session_b.close()
