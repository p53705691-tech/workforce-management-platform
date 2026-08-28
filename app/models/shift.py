"""Shift model — planned work.

A ``Shift`` represents planned work, not actual attendance (attendance is
a later milestone). One row covers the whole shift including overnight
ones (e.g. 22:00 -> 06:00 the next day is a single row, never two).

``business_date`` is the attribution date used for daily overtime and
"who's working today" reporting. Per the project's confirmed rule (A1),
it is the local date of ``starts_at`` in the organization's timezone —
an overnight shift is attributed entirely to its start date. It is
computed and set by the service layer at creation time, not derived by
the database, since it depends on the organization's timezone.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class Shift(TimestampMixin, db.Model):
    __tablename__ = "shifts"
    __table_args__ = (
        # Target for the composite FK from attendance_entries.(shift_id,
        # organization_id) — same "child table needs the parent's
        # composite unique target" pattern already used for
        # departments/employees.
        UniqueConstraint("id", "organization_id"),
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        # Composite FK: a shift's department must belong to the same
        # organization as the shift itself (cross-tenant guard).
        ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            ondelete="RESTRICT",
        ),
        # Composite FK: an assigned employee must belong to the same
        # organization as the shift. NULL employee_id (an open/unassigned
        # shift) bypasses this check entirely.
        ForeignKeyConstraint(
            ["employee_id", "organization_id"],
            ["employees.id", "employees.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        # Composite FK: an assigned job location (MULTI_SITE /
        # SHIFT_JOB_LOCATION clock-in validation, see
        # app.models.organization) must belong to the same organization
        # as the shift. NULL bypasses this entirely — most shifts never
        # set one, including every shift for an organization whose
        # location_validation_mode is NONE/FIXED_SITE/MOBILE.
        ForeignKeyConstraint(
            ["job_location_id", "organization_id"],
            ["job_locations.id", "job_locations.organization_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        CheckConstraint("break_minutes >= 0", name="break_minutes_non_negative"),
        # A break cannot consume the entire shift: the break, in seconds,
        # must be strictly less than the shift's total duration.
        CheckConstraint(
            "break_minutes * 60 < EXTRACT(EPOCH FROM (ends_at - starts_at))",
            name="break_minutes_less_than_duration",
        ),
        # Sanity cap (confirmed rule A7): no single shift may span more
        # than 24 hours, overnight or not.
        CheckConstraint(
            "ends_at - starts_at <= interval '24 hours'",
            name="duration_max_24_hours",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'cancelled')", name="status_valid"
        ),
        CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)",
            name="published_at_matches_status",
        ),
        # Core data-integrity guarantee: an employee cannot be booked onto
        # two overlapping shifts. Cancelled shifts and unassigned
        # (employee_id IS NULL) shifts are excluded from the check.
        ExcludeConstraint(
            ("employee_id", "="),
            (func.tstzrange(column("starts_at"), column("ends_at")), "&&"),
            name="ex_shifts_employee_no_overlap",
            where=text("employee_id IS NOT NULL AND status <> 'cancelled'"),
            using="gist",
        ),
        Index(
            "ix_shifts_organization_id_department_id_starts_at",
            "organization_id",
            "department_id",
            "starts_at",
        ),
        Index("ix_shifts_employee_id_starts_at", "employee_id", "starts_at"),
        Index(
            "ix_shifts_organization_id_business_date",
            "organization_id",
            "business_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    department_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    starts_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    business_date: Mapped[object] = mapped_column(Date, nullable=False)
    break_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    job_location_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:
        return f"<Shift id={self.id} status={self.status!r}>"
