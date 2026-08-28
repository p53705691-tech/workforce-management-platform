"""Login business logic: credential checking, lockout, and password reset.

Kept out of the route handler so the account-lockout rule (a genuine
business rule, not HTTP plumbing) is independently testable and reusable.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.auth.passwords import hash_password, verify_password
from app.extensions import db
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services import audit as audit_service
from app.services import notifications as notification_service
from app.services.errors import ValidationError

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


def change_password(user: User, current_password: str, new_password: str) -> None:
    """Change the signed-in ``user``'s own password.

    Requires re-entering the current password — standard defense
    against a hijacked, still-logged-in session being used to lock the
    real account owner out permanently. Not role-restricted: any
    authenticated user may change their own password, regardless of
    role, since this is a property of the login itself, not the
    Employee domain.
    """
    if not verify_password(user.password_hash, current_password):
        raise ValidationError(
            "Current password is incorrect.", field="current_password"
        )

    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    audit_service.record(
        "password_changed",
        "user",
        entity_id=user.id,
        organization_id=user.organization_id,
        actor_user_id=user.id,
    )
    # One commit covers both the password change and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()


# 256 bits of entropy via secrets.token_urlsafe — the raw token is never
# stored anywhere (see app.models.password_reset_token's module
# docstring), only its SHA-256 hash, so this is the sole source of the
# value that goes into the emailed reset link.
_RESET_TOKEN_BYTES = 32
_RESET_TOKEN_LIFETIME = timedelta(minutes=30)

# Same "if that account exists" phrasing as GENERIC_LOGIN_ERROR's
# anti-enumeration intent above: a request for a nonexistent, inactive,
# or role-mismatched email must be indistinguishable from a real one
# that just triggered an email send.
GENERIC_RESET_REQUESTED_MESSAGE = (
    "If an account exists for that email, a reset link has been sent."
)


def _hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def request_password_reset(email: str) -> None:
    """Issue a password-reset token and email it, if ``email`` matches a
    real, active account. Always returns normally either way — the route
    layer shows ``GENERIC_RESET_REQUESTED_MESSAGE`` regardless of which
    branch ran here, so a caller can never use response differences to
    enumerate valid accounts (same anti-enumeration principle as
    ``authenticate``, just without the timing-parity concern: this path
    already does real, roughly-constant work — a query plus, on match, a
    token insert — regardless of outcome, unlike login's Argon2 cost
    asymmetry).
    """
    user = db.session.query(User).filter(User.email == email).one_or_none()
    if user is None or not user.is_active:
        return

    raw_token = secrets.token_urlsafe(_RESET_TOKEN_BYTES)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_reset_token(raw_token),
        expires_at=datetime.now(timezone.utc) + _RESET_TOKEN_LIFETIME,
    )
    db.session.add(reset_token)
    audit_service.record(
        "password_reset_requested",
        "user",
        entity_id=user.id,
        organization_id=user.organization_id,
    )
    # One commit covers both the token insert and the audit entry above —
    # see app.services.audit's module docstring. The email is sent only
    # after this commit succeeds — see app.services.notifications's
    # module docstring on why a notification must never be sent from
    # inside an uncommitted transaction.
    db.session.commit()

    notification_service.send_email(
        user.email,
        "Reset your password",
        "password_reset",
        organization_name=_organization_name(user.organization_id),
        login_email=user.email,
        raw_token=raw_token,
    )


def _organization_name(organization_id: int) -> str:
    # Imported here, not at module level: app.services.scheduling imports
    # this module transitively via other services, and organization.py
    # itself has no such cycle, but this keeps the pattern consistent
    # with app.services.audit.list_entries's identical local-import note.
    from app.models.organization import Organization

    organization = db.session.get(Organization, organization_id)
    return organization.name if organization is not None else ""


def reset_password(raw_token: str, new_password: str) -> None:
    """Redeem a password-reset token, setting ``new_password`` for the
    account it was issued to.

    Raises ``ValidationError`` for any invalid token (never found,
    already used, or expired) with one single generic message — same
    anti-enumeration principle as everywhere else in this module: a
    caller must not be able to distinguish "this token never existed"
    from "this token expired ten minutes ago."

    Also clears any lockout and bumps ``password_changed_at``, which
    ``app.models.user.load_user`` already treats as the enforcement point
    for invalidating every other still-live session for this account —
    the same mechanism ``change_password`` above relies on.
    """
    token_hash = _hash_reset_token(raw_token)
    reset_token = (
        db.session.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .one_or_none()
    )

    invalid_message = "This password reset link is invalid or has expired."
    now = datetime.now(timezone.utc)
    if (
        reset_token is None
        or reset_token.used_at is not None
        or reset_token.expires_at <= now
    ):
        raise ValidationError(invalid_message)

    user = db.session.get(User, reset_token.user_id)
    if user is None or not user.is_active:
        raise ValidationError(invalid_message)

    reset_token.used_at = now
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    audit_service.record(
        "password_reset_completed",
        "user",
        entity_id=user.id,
        organization_id=user.organization_id,
        actor_user_id=user.id,
    )
    # One commit covers the token consumption, the password change, and
    # the audit entry above — see app.services.audit's module docstring.
    db.session.commit()
