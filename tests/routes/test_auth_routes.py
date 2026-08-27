from datetime import datetime, timedelta, timezone

import pytest
from flask import g
from freezegun import freeze_time

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


def test_session_expiry_is_absolute_not_extended_by_activity(client, db_session):
    """Security-review finding: SESSION_REFRESH_EACH_REQUEST defaults to
    True, which re-signs the session cookie with a fresh expiry on every
    response for a permanent session — turning the documented "expires
    12 hours after login regardless of use" into a 12-hour *idle*
    timeout that an actively-used stolen cookie would never actually
    hit. Reproduced here: an authenticated request made partway through
    the window must not push the expiry back.
    """
    user = _make_login_user(db_session)

    with freeze_time("2026-01-01 00:00:00"):
        client.post("/login", data={"email": user.email, "password": PASSWORD})

    with freeze_time("2026-01-01 06:00:00"):
        # Activity partway through the 12-hour window -- under the old
        # sliding behavior this would have pushed the expiry to 18:00.
        _forget_cached_current_user()
        assert client.get("/").status_code == 302

    with freeze_time("2026-01-01 12:00:01"):
        # Just past 12 hours from the *original* login. Still well
        # within what a sliding expiry (refreshed at 06:00) would allow.
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


def test_user_can_change_their_own_password(client, db_session):
    from app.auth.passwords import verify_password
    from app.models.user import User

    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    response = client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    updated = db_session.query(User).filter_by(id=user.id).one()
    assert verify_password(updated.password_hash, "a-brand-new-password")


def test_changing_own_password_does_not_end_the_current_session(client, db_session):
    """The session performing a legitimate self-service password change
    must keep working immediately afterward — see app.models.user.
    load_user's docstring on why its own session stamp is refreshed by
    app.routes.auth.change_password_route rather than only at the next
    login.
    """
    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})
    _forget_cached_current_user()

    client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )
    _forget_cached_current_user()

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" not in response.headers["Location"]


def test_changing_password_signs_out_a_different_existing_session(client, db_session):
    """A password change (self-service or admin reset) must invalidate
    any *other* already-established session for the same account, not
    just block future logins with the old password.
    """
    user = _make_login_user(db_session)
    other_client = client.application.test_client()

    client.post("/login", data={"email": user.email, "password": PASSWORD})
    _forget_cached_current_user()
    other_client.post("/login", data={"email": user.email, "password": PASSWORD})
    _forget_cached_current_user()

    client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )
    _forget_cached_current_user()

    response = other_client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_wrong_current_password_is_rejected(client, db_session):
    from app.auth.passwords import verify_password
    from app.models.user import User

    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    response = client.post(
        "/change-password",
        data={
            "current_password": "totally wrong password",
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Current password is incorrect" in body
    unchanged = db_session.query(User).filter_by(id=user.id).one()
    assert verify_password(unchanged.password_hash, PASSWORD)


def test_mismatched_confirmation_is_rejected(client, db_session):
    from app.auth.passwords import verify_password
    from app.models.user import User

    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    response = client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-different-password",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    unchanged = db_session.query(User).filter_by(id=user.id).one()
    assert verify_password(unchanged.password_hash, PASSWORD)


def test_short_new_password_is_rejected(client, db_session):
    from app.auth.passwords import verify_password
    from app.models.user import User

    user = _make_login_user(db_session)
    client.post("/login", data={"email": user.email, "password": PASSWORD})

    response = client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "short",
            "confirm_new_password": "short",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    unchanged = db_session.query(User).filter_by(id=user.id).one()
    assert verify_password(unchanged.password_hash, PASSWORD)


def test_admin_can_reach_the_account_page_and_change_their_password(client, db_session):
    """Security/QA finding: admin and manager had no reachable page to
    change their own password from at all, even though the underlying
    route (change_password_route) was never role-restricted.
    """
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    client.post("/login", data={"email": admin.email, "password": PASSWORD})

    get_response = client.get("/account")
    assert get_response.status_code == 200
    assert b"Change Password" in get_response.data

    post_response = client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
        follow_redirects=True,
    )

    assert post_response.status_code == 200
    from app.auth.passwords import verify_password
    from app.models.user import User

    updated = db_session.query(User).filter_by(id=admin.id).one()
    assert verify_password(updated.password_hash, "a-brand-new-password")


def test_anonymous_user_cannot_reach_the_account_page(client):
    response = client.get("/account")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_anonymous_user_cannot_change_password(client, db_session):
    response = client.post(
        "/change-password",
        data={
            "current_password": "whatever",
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
