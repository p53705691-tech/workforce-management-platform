"""LeaveRequest model — an employee's request for time off.

Leave balances/accrual are not tracked in the MVP (confirmed rule for
this milestone): this table records requests and their approval
lifecycle only, never a "days remaining" concept.

Partial-day leave is permitted — ``starts_at``/``ends_at`` are
``timestamptz``-ranged, consistent with how shifts/attendance already
work, not restricted to whole calendar days.

Ambiguity resolved during implementation: the spec's literal CHECK
``(status IN ('approved','rejected')) = (decided_by_user_id IS NOT NULL
AND decided_at IS NOT NULL)`` conflicts with the confirmed rule that an
approved-then-cancelled request must stay distinguishable from a
pending-then-cancelled one using the existing ``status`` column alone (no
new column). Taken literally, that CHECK is a strict biconditional against
the *current* status, so cancelling a previously-approved request (status
becomes ``'cancelled'``, which is not in ``('approved', 'rejected')``)
would force ``decided_by_user_id``/``decided_at`` back to NULL, erasing
exactly the history the business rule needs kept. ``'cancelled'`` can be
reached from either ``'pending'`` (never decided) or ``'approved'``
(decided, then reversed), so a single current-status value cannot
determine what the decision fields should be for that case — the
constraint is split into two, below: one that always keeps the pair of
decision fields consistent (both present or both absent, regardless of
status), and one that ties decision-field presence to status only for
``'pending'``/``'approved'``/``'rejected'`` (a pending request never has
decision fields; an approved/rejected one always does), leaving
``'cancelled'`` rows free to carry over whichever state they had before
cancellation. ``cancel_leave`` (see ``app.services.leave``) relies on this:
it never touches ``decided_by_user_id``/``decided_at``, so a cancelled
request's decision fields are exactly the record of what happened before
cancellation.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class LeaveRequest(TimestampMixin, db.Model):
    __tablename__ = "leave_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        # Composite FK: the employee must belong to the same organization
        # as the request itself (cross-tenant guard, same pattern as
        # shifts/attendance entries).
        ForeignKeyConstraint(
            ["employee_id", "organization_id"],
            ["employees.id", "employees.organization_id"],
            ondelete="RESTRICT",
        ),
        # Composite FK: the leave type must belong to the same
        # organization as the request itself.
        ForeignKeyConstraint(
            ["leave_type_id", "organization_id"],
            ["leave_types.id", "leave_types.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="status_valid",
        ),
        # The decision fields are always both present or both absent,
        # regardless of status — see the module docstring for why this is
        # split out from the status-matching check below.
        CheckConstraint(
            "(decided_by_user_id IS NULL) = (decided_at IS NULL)",
            name="decision_fields_paired",
        ),
        # Decision-field presence matches status only for 'pending' (never
        # decided) and 'approved'/'rejected' (always decided). A
        # 'cancelled' row is exempt: it carries over whatever decision
        # state it had before cancellation (see module docstring).
        CheckConstraint(
            "status = 'cancelled' OR "
            "(status IN ('approved', 'rejected')) = (decided_by_user_id IS NOT NULL)",
            name="decision_matches_status",
        ),
        # No overlapping pending/approved leave for the same employee.
        # Rejected/cancelled requests are excluded from the check, mirroring
        # how a cancelled shift never blocks a new one. Hand-written to
        # match what postgresql.ExcludeConstraint compiles to here
        # (autogenerate cannot produce this DDL) — verified against
        # pg_constraint once applied, same pattern as
        # app.models.shift.Shift's ex_shifts_employee_no_overlap.
        ExcludeConstraint(
            ("employee_id", "="),
            (func.tstzrange(column("starts_at"), column("ends_at")), "&&"),
            name="ex_leave_requests_employee_no_overlap",
            where=text("status IN ('pending', 'approved')"),
            using="gist",
        ),
        Index("ix_leave_requests_employee_id_starts_at", "employee_id", "starts_at"),
        Index("ix_leave_requests_organization_id_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    leave_type_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    starts_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LeaveRequest id={self.id} status={self.status!r}>"
