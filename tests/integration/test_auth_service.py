"""Integration tests for app.auth.service.authenticate's lockout policy.

See tests/integration/test_auth_service_timing.py for the separate
timing-parity tests, and tests/integration/test_audit_service.py for the
login-auditing and audit-transaction-atomicity tests.
"""

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from app.auth.passwords import verify_password
from app.auth.service import (
    MAX_FAILED_LOGIN_ATTEMPTS,
    authenticate,
    change_password,
    request_password_reset,
    reset_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.services.errors import ValidationError
from tests.factories import make_organization, make_user

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery staple"


def _lock_out(user, db_session):
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        authenticate(user.email, "wrong password")
    db_session.refresh(user)
    assert user.locked_until is not None


class TestFailedLoginCountResetAfterLockoutExpires:
    def test_a_single_wrong_guess_after_lockout_expires_does_not_immediately_relock(
        self, db_session
    ):
        """Round B fix: once ``locked_until`` has passed, a wrong-password
        attempt must start a *fresh* count from this failure, not keep
        incrementing the stale (already >= MAX_FAILED_LOGIN_ATTEMPTS)
        count -- otherwise a single further wrong guess re-locks the
        account for another full lockout duration, indefinitely, long
        after the original lockout window ended.
        """
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        with freeze_time("2026-01-01 00:00:00"):
            _lock_out(user, db_session)

        # Well past the 15-minute lockout window.
        with freeze_time("2026-01-01 01:00:00"):
            result = authenticate(user.email, "still wrong")

        db_session.refresh(user)
        assert result.success is False
        assert user.failed_login_count == 1
        assert user.locked_until is None

        # Only re-locks after a fresh run of MAX_FAILED_LOGIN_ATTEMPTS
        # further failures, not after just one more.
        with freeze_time("2026-01-01 01:00:01"):
            for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 2):
                authenticate(user.email, "still wrong")
            db_session.refresh(user)
            assert user.locked_until is None

            authenticate(user.email, "still wrong")
            db_session.refresh(user)
            assert user.locked_until is not None

    def test_a_correct_password_after_lockout_expires_resets_the_count(
        self, db_session
    ):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        with freeze_time("2026-01-01 00:00:00"):
            _lock_out(user, db_session)

        with freeze_time("2026-01-01 01:00:00"):
            result = authenticate(user.email, PASSWORD)

        db_session.refresh(user)
        assert result.success is True
        assert user.failed_login_count == 0
        assert user.locked_until is None

    def test_still_within_the_lockout_window_a_wrong_guess_stays_locked(
        self, db_session
    ):
        """Sanity check: the reset only applies once locked_until has
        actually passed -- it must not weaken the lockout itself.
        """
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        with freeze_time("2026-01-01 00:00:00"):
            _lock_out(user, db_session)
            locked_until_before = user.locked_until

        with freeze_time("2026-01-01 00:05:00"):
            authenticate(user.email, "still wrong")

        db_session.refresh(user)
        assert user.locked_until == locked_until_before


class TestChangePassword:
    def test_changes_the_password_when_current_password_is_correct(self, db_session):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        change_password(user, PASSWORD, "a-brand-new-password")

        assert verify_password(user.password_hash, "a-brand-new-password")
        assert not verify_password(user.password_hash, PASSWORD)

    def test_rejects_an_incorrect_current_password(self, db_session):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        with pytest.raises(ValidationError):
            change_password(user, "wrong current password", "a-brand-new-password")

        assert verify_password(user.password_hash, PASSWORD)

    def test_updates_password_changed_at(self, db_session):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        original_changed_at = user.password_changed_at

        with freeze_time("2026-06-01 12:00:00"):
            change_password(user, PASSWORD, "a-brand-new-password")

        assert user.password_changed_at != original_changed_at


def _requested_reset_token(db_session, monkeypatch, email):
    """Call ``request_password_reset`` and capture the raw token that
    would have been emailed, via ``notification_service.send_email``'s
    ``raw_token`` kwarg — the DB only ever stores the token's hash (see
    app.models.password_reset_token's module docstring), so this is the
    only way a test can recover the actual value a real link would carry.
    """
    captured = {}

    def _fake_send_email(to, subject, template_name, **context):
        captured["to"] = to
        captured["raw_token"] = context["raw_token"]

    monkeypatch.setattr(
        "app.auth.service.notification_service.send_email", _fake_send_email
    )
    request_password_reset(email)
    return captured.get("raw_token")


class TestPasswordReset:
    def test_request_then_reset_changes_the_password(self, db_session, monkeypatch):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        raw_token = _requested_reset_token(db_session, monkeypatch, user.email)
        assert raw_token is not None

        reset_password(raw_token, "a-brand-new-password")

        db_session.refresh(user)
        assert verify_password(user.password_hash, "a-brand-new-password")
        assert not verify_password(user.password_hash, PASSWORD)

    def test_request_for_unknown_email_sends_nothing_and_does_not_raise(
        self, db_session, monkeypatch
    ):
        raw_token = _requested_reset_token(
            db_session, monkeypatch, "nobody@example.test"
        )
        assert raw_token is None

    def test_request_for_inactive_account_sends_nothing(self, db_session, monkeypatch):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        user.is_active = False
        db_session.flush()

        raw_token = _requested_reset_token(db_session, monkeypatch, user.email)
        assert raw_token is None

    def test_reset_with_unknown_token_raises_generic_error(self, db_session):
        with pytest.raises(ValidationError):
            reset_password("not-a-real-token", "a-brand-new-password")

    def test_reset_with_expired_token_raises_and_does_not_change_password(
        self, db_session, monkeypatch
    ):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        with freeze_time("2026-01-01 00:00:00"):
            raw_token = _requested_reset_token(db_session, monkeypatch, user.email)

        with freeze_time("2026-01-01 01:00:00"):
            with pytest.raises(ValidationError):
                reset_password(raw_token, "a-brand-new-password")

        db_session.refresh(user)
        assert verify_password(user.password_hash, PASSWORD)

    def test_reset_token_is_single_use(self, db_session, monkeypatch):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        raw_token = _requested_reset_token(db_session, monkeypatch, user.email)

        reset_password(raw_token, "a-brand-new-password")

        with pytest.raises(ValidationError):
            reset_password(raw_token, "yet-another-password")

        db_session.refresh(user)
        assert verify_password(user.password_hash, "a-brand-new-password")

    def test_reset_marks_the_token_used(self, db_session, monkeypatch):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        raw_token = _requested_reset_token(db_session, monkeypatch, user.email)

        reset_password(raw_token, "a-brand-new-password")

        token_row = (
            db_session.query(PasswordResetToken)
            .filter(PasswordResetToken.user_id == user.id)
            .one()
        )
        assert token_row.used_at is not None

    def test_reset_clears_an_existing_lockout(self, db_session, monkeypatch):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        _lock_out(user, db_session)
        raw_token = _requested_reset_token(db_session, monkeypatch, user.email)

        reset_password(raw_token, "a-brand-new-password")

        db_session.refresh(user)
        assert user.locked_until is None
        assert user.failed_login_count == 0

    def test_reset_invalidates_other_live_sessions(self, db_session, monkeypatch):
        """``password_changed_at`` bumps, which app.models.user.load_user
        already treats as the enforcement point for rejecting a session
        established before the change — same mechanism change_password
        relies on (see TestChangePassword.test_updates_password_changed_at).
        """
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        original_changed_at = user.password_changed_at
        raw_token = _requested_reset_token(db_session, monkeypatch, user.email)

        reset_password(raw_token, "a-brand-new-password")

        db_session.refresh(user)
        assert user.password_changed_at != original_changed_at
