"""Round A fix: login must not be measurably faster for a nonexistent,
inactive, or locked account than for a real account with a wrong
password -- otherwise an attacker can time responses to enumerate valid
emails, defeating GENERIC_LOGIN_ERROR's generic wording.

Rather than asserting on wall-clock timing (flaky in CI), these tests
spy on ``verify_password`` and assert it is actually invoked (against
the fixed dummy hash) on every early-return path that doesn't already
have a real hash to check.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.auth import service as auth_service
from tests.factories import make_organization, make_user

pytestmark = pytest.mark.integration


def _spy_on_verify_password(monkeypatch):
    spy = MagicMock(wraps=auth_service.verify_password)
    monkeypatch.setattr(auth_service, "verify_password", spy)
    return spy


class TestLoginTimingParity:
    def test_nonexistent_email_still_performs_a_dummy_password_verification(
        self, db_session, monkeypatch
    ):
        spy = _spy_on_verify_password(monkeypatch)

        auth_service.authenticate("nobody@example.com", "whatever-password")

        spy.assert_called_once_with(
            auth_service._DUMMY_PASSWORD_HASH, "whatever-password"
        )

    def test_inactive_account_still_performs_a_dummy_password_verification(
        self, db_session, monkeypatch
    ):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, is_active=False)
        spy = _spy_on_verify_password(monkeypatch)

        auth_service.authenticate(user.email, "whatever-password")

        spy.assert_called_once_with(
            auth_service._DUMMY_PASSWORD_HASH, "whatever-password"
        )

    def test_locked_account_still_performs_a_dummy_password_verification(
        self, db_session, monkeypatch
    ):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org)
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        db_session.flush()
        spy = _spy_on_verify_password(monkeypatch)

        auth_service.authenticate(user.email, "whatever-password")

        spy.assert_called_once_with(
            auth_service._DUMMY_PASSWORD_HASH, "whatever-password"
        )

    def test_wrong_password_for_a_real_account_verifies_against_its_own_hash(
        self, db_session, monkeypatch
    ):
        """Sanity check: the real, existing-account path must keep using
        the account's own hash, not silently switch to the dummy one.
        """
        org = make_organization(db_session)
        user = make_user(
            db_session, organization=org, password="correct horse battery staple"
        )
        spy = _spy_on_verify_password(monkeypatch)

        auth_service.authenticate(user.email, "wrong-password")

        spy.assert_called_once_with(user.password_hash, "wrong-password")
