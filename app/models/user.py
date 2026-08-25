"""User model — authentication and authorization identity.

A ``User`` (login account) is distinct from an ``Employee`` (HR record).
Admin and manager users may exist without a linked employee record;
``role='employee'`` users must be linked, which is enforced at the
database layer by a CHECK constraint, not just in application code.
"""

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db, login_manager
from app.models.base import TimestampMixin


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        # Composite FK: a linked employee must belong to the same
        # organization as the login itself. NULL employee_id (admins,
        # managers without an HR record) is not checked by this FK at all.
        ForeignKeyConstraint(
            ["employee_id", "organization_id"],
            ["employees.id", "employees.organization_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("role IN ('admin', 'manager', 'employee')", name="role_valid"),
        CheckConstraint(
            "role <> 'employee' OR employee_id IS NOT NULL",
            name="employee_role_requires_employee_id",
        ),
        CheckConstraint(
            "failed_login_count >= 0", name="failed_login_count_non_negative"
        ),
        # Target for the composite FK from
        # department_managers.(user_id, organization_id) — same "child
        # table needs the parent's composite unique target" pattern
        # already used by departments/employees/shifts.
        UniqueConstraint("id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, unique=True
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    last_login_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    locked_until: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


@login_manager.user_loader
def load_user(user_id: str) -> "User | None":
    """Load the session's user, or invalidate the session outright.

    Returning ``None`` here (rather than the row itself) makes
    Flask-Login treat the *current* request as unauthenticated, which is
    what actually forces re-authentication the moment an account is
    deactivated or locked out — there is no separate session-tracking
    table in this project, so this check on every request is the
    enforcement point. A stale cookie for a deactivated/locked account is
    otherwise honored right up until it expires on its own.
    """
    user = db.session.get(User, int(user_id))
    if user is None:
        return None
    if not user.is_active:
        return None
    if user.locked_until is not None and user.locked_until > datetime.now(timezone.utc):
        return None
    return user
