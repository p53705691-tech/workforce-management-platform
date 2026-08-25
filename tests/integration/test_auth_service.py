"""Integration tests for app.auth.service.authenticate's lockout policy.

See tests/integration/test_auth_service_timing.py for the separate
timing-parity tests, and tests/integration/test_audit_service.py for the
login-auditing and audit-transaction-atomicity tests.
"""

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from app.auth.service import MAX_FAILED_LOGIN_ATTEMPTS, authenticate
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
