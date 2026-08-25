from datetime import datetime, timedelta, timezone

import pytest
from flask import g

from tests.factories import make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _make_login_user(db_session, **overrides):
    org = make_organization(db_session)
    return make_user(db_session, organization=org, password=PASSWORD, **overrides)


def test_successful_login_redirects_and_sets_session(client, db_session):
    user = _make_login_user(db_session)

    response = client.post(
        "/login", data={"email": user.email, "password": PASSWORD}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    with client.session_transaction() as sess:
        assert sess["_user_id"] == str(user.id)


def test_login_regenerates_the_session(client, db_session):
    user = _make_login_user(db_session)

    # Establish an anonymous session cookie first.
    client.get("/login")
    cookie_before = client.get_cookie("session")

    client.post("/login", data={"email": user.email, "password": PASSWORD})
    cookie_after = client.get_cookie("session")

    assert cookie_before is None or cookie_after.value != cookie_before.value

    with client.session_transaction() as sess:
        # Flask-Login writes a fresh random identifier on every successful
        # login, which is what actually changes the signed session cookie
        # value (session fixation defense for a stateless cookie session).
        assert "_id" in sess


def test_wrong_password_shows_generic_error(client, db_session):
    user = _make_login_user(db_session)

    response = client.post(
        "/login", data={"email": user.email, "password": "not the password"}
    )

    assert response.status_code == 200
    assert b"Invalid email or password." in response.data


def test_nonexistent_email_shows_the_same_generic_error(client, db_session):
    response = client.post(
        "/login", data={"email": "nobody@example.com", "password": "whatever"}
    )

    assert response.status_code == 200
    assert b"Invalid email or password." in response.data


def test_five_failed_attempts_locks_the_account(client, db_session):
    user = _make_login_user(db_session)

    for _ in range(5):
        client.post("/login", data={"email": user.email, "password": "wrong"})

    # A 6th attempt with the *correct* password must still be rejected
    # because the account is now locked.
    response = client.post(
        "/login", data={"email": user.email, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert b"Invalid email or password." in response.data

    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_missing_csrf_token_is_rejected(client, db_session, app):
    user = _make_login_user(db_session)

    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            "/login", data={"email": user.email, "password": PASSWORD}
        )
    finally:
        app.config["WTF_CSRF_ENABLED"] = False

    assert response.status_code == 400


def test_next_pointing_at_external_host_is_rejected(client, db_session):
    user = _make_login_user(db_session)

    response = client.post(
        "/login?next=https://evil.example/phish",
        data={"email": user.email, "password": PASSWORD},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_next_with_relative_path_is_honored(client, db_session):
    user = _make_login_user(db_session)

    response = client.post(
        "/login?next=/some/relative/path",
        data={"email": user.email, "password": PASSWORD},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/some/relative/path"


def _forget_cached_current_user():
    """Drop Flask-Login's per-``g`` ``current_user`` cache.

    The ``app`` fixture keeps a single app context pushed for the whole
    test session (see the ``client`` fixture's own docstring), so ``g`` —
    and with it Flask-Login's ``g._login_user`` cache — would otherwise
    survive across multiple ``client.get()`` calls *within one test* too,
    not just between tests. A real production request always starts with
    a fresh ``g``, so without this a test issuing more than one request
    against the same logged-in session would spuriously see the first
    request's cached user on every later request, regardless of any
    account state change made in between.
    """
    g.pop("_login_user", None)


def test_existing_session_stops_working_once_the_account_is_locked_out(
    client, db_session
):
    """Round B fix: app.models.user.load_user now rejects a locked-out
    user on the very next request, rather than only blocking new logins —
    there is no separate session-tracking table, so this check on every
    request is the actual enforcement point for revoking an already-
    established session.
    """
    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    # The session is valid immediately after login.
    assert client.get("/").status_code == 302
    _forget_cached_current_user()

    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    db_session.flush()
    _forget_cached_current_user()

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_existing_session_stops_working_once_the_account_is_deactivated(
    client, db_session
):
    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    assert client.get("/").status_code == 302
    _forget_cached_current_user()

    user.is_active = False
    db_session.flush()
    _forget_cached_current_user()

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logout_clears_session(client, db_session):
    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    with client.session_transaction() as sess:
        assert sess["_user_id"] == str(user.id)

    logout_response = client.post("/logout")
    assert logout_response.status_code == 302

    with client.session_transaction() as sess:
        assert "_user_id" not in sess

    protected_response = client.get("/")
    assert protected_response.status_code == 302
    assert "/login" in protected_response.headers["Location"]
