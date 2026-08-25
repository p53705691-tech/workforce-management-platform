"""Login business logic: credential checking and lockout.

Kept out of the route handler so the account-lockout rule (a genuine
business rule, not HTTP plumbing) is independently testable and reusable.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.auth.passwords import hash_password, verify_password
from app.extensions import db
from app.models.user import User
from app.services import audit as audit_service

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

# Deliberately identical whether the email doesn't exist, the account is
# inactive/locked, or the password is wrong — never reveal which case
# applies (no user enumeration).
GENERIC_LOGIN_ERROR = "Invalid email or password."

# A fixed, module-level Argon2 hash with no corresponding real account,
# hashed once at import time. Every early-return path below (no such
# user, inactive account, locked account) runs a verification against
# this dummy hash before returning, discarding the result, so it costs
# roughly the same argon2 work as the "account exists, wrong password"
# path. Without this, an attacker could time responses to distinguish
# "no such account" (fast, no verification) from "wrong password"
# (slow, real verification) and enumerate valid emails.
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-account-timing-parity-only")


def _burn_dummy_verification_time(password: str) -> None:
    """Run a real argon2 verification against a fixed dummy hash.

    Called (and its result discarded) on every login failure path that
    doesn't already perform a real ``verify_password`` call, purely to
    keep response timing consistent across all failure reasons.
    """
    verify_password(_DUMMY_PASSWORD_HASH, password)


@dataclass(frozen=True)
class LoginResult:
    success: bool
    user: User | None
    error: str | None


def authenticate(email: str, password: str) -> LoginResult:
    """Validate credentials and apply the lockout policy.

    On failure, always returns ``GENERIC_LOGIN_ERROR`` regardless of the
    reason, and persists any lockout-related state changes (failed
    attempt count, lock expiry) before returning.

    Every branch below stages its audit entry with ``audit_service.record``
    (add-only, see that module's docstring) and then issues exactly one
    commit that covers both the audit row and whatever primary state this
    function itself changed — never a commit followed by a separate
    ``record`` call, and never a ``record`` call with no commit at all.
    Round A applied this same "audit shares the primary write's
    transaction" fix to every other privileged-write call site
    (``pay_rates``/``employees``/``attendance``/``leave``/``scheduling``)
    but explicitly left this module out of scope; this closes that gap
    here too, so a crash between two separate commits can never leave a
    lockout/login state change persisted with no audit trail (or, for the
    three no-primary-write branches below, leave the audit entry staged
    but never actually committed at all).
    """
    user = db.session.query(User).filter(User.email == email).one_or_none()
    now = datetime.now(timezone.utc)

    if user is None:
        # No real hash to verify against, but a login attempt against a
        # nonexistent account must still pay the same argon2 cost as a
        # wrong-password attempt against a real one (see
        # _burn_dummy_verification_time) — otherwise this path is
        # measurably faster and an attacker can enumerate valid emails
        # by timing responses, defeating GENERIC_LOGIN_ERROR's intent.
        _burn_dummy_verification_time(password)
        # No organization/user context exists at all for an unrecognized
        # email — both stay NULL on the audit row (see
        # app.models.audit_log's docstring on exactly this case).
        audit_service.record(
            "login_failed", "user", changes={"reason": "no_such_account"}
        )
        db.session.commit()
        return LoginResult(False, None, GENERIC_LOGIN_ERROR)

    if not user.is_active:
        _burn_dummy_verification_time(password)
        audit_service.record(
            "login_failed",
            "user",
            entity_id=user.id,
            organization_id=user.organization_id,
            changes={"reason": "inactive_account"},
        )
        db.session.commit()
        return LoginResult(False, None, GENERIC_LOGIN_ERROR)

    if user.locked_until is not None and user.locked_until > now:
        _burn_dummy_verification_time(password)
        audit_service.record(
            "login_failed",
            "user",
            entity_id=user.id,
            organization_id=user.organization_id,
            changes={"reason": "account_locked"},
        )
        db.session.commit()
        return LoginResult(False, None, GENERIC_LOGIN_ERROR)

    if not verify_password(user.password_hash, password):
        if user.locked_until is not None and user.locked_until <= now:
            # The lockout window has fully elapsed. Without this reset, a
            # single further wrong guess would increment the still-stale
            # (>= MAX_FAILED_LOGIN_ATTEMPTS) count right back over the
            # threshold and re-lock the account for another full
            # LOCKOUT_DURATION — indefinitely, from just one wrong guess
            # every lockout period, long after the original lockout ended.
            # Treat this failure as the first of a fresh run instead.
            user.failed_login_count = 0
            user.locked_until = None
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = now + LOCKOUT_DURATION
        # actor_user_id stays NULL: the password check failed, so this
        # request never actually authenticated as this account, even
        # though the account itself (and its organization) is known.
        audit_service.record(
            "login_failed",
            "user",
            entity_id=user.id,
            organization_id=user.organization_id,
            changes={"reason": "bad_password"},
        )
        db.session.commit()
        return LoginResult(False, None, GENERIC_LOGIN_ERROR)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    audit_service.record(
        "login_success",
        "user",
        entity_id=user.id,
        organization_id=user.organization_id,
        actor_user_id=user.id,
    )
    db.session.commit()
    return LoginResult(True, user, None)
