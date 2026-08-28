"""AttendanceEntry model — actual work, distinct from ``Shift`` (planned work).

One row per continuous work period, including overnight ones (e.g. 22:10
-> 06:05 the next day is a single row, never two) — same "one row per
continuous span" convention already used for shifts.

``business_date`` is the attribution date used for daily overtime and
"who worked today" reporting. Per the project's confirmed rule (A1),
applied here for consistency with shifts, it is the local date of
``started_at`` in the organization's timezone. It is computed and set by
the service layer at creation time, not derived by the database, since it
depends on the organization's timezone.

Ambiguity resolved during implementation: the spec's literal CHECK
``(status = 'open') = (ended_at IS NULL)`` conflicts with confirmed rule
A11 (``flag_stale_open_entries`` sets ``status='needs_review'`` on a stale
entry while explicitly never inventing an ``ended_at``). Taken literally,
a ``needs_review`` row with a NULL ``ended_at`` would violate that CHECK.
The constraint below instead treats ``open`` and ``needs_review`` as the
same "not yet closed" state for the purposes of ``ended_at`` nullability
-- ``ended_at`` is NULL if and only if the entry isn't closed -- which
preserves the real invariant (only a closed entry has an end time) without
contradicting A11. ``status_valid`` still restricts status to exactly
these three values.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    Text,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class AttendanceEntry(TimestampMixin, db.Model):
    __tablename__ = "attendance_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        # Composite FK: the employee must belong to the same organization
        # as the entry itself (cross-tenant guard, same pattern as shifts).
        ForeignKeyConstraint(
            ["employee_id", "organization_id"],
            ["employees.id", "employees.organization_id"],
            ondelete="RESTRICT",
        ),
        # Composite FK: a matched shift must belong to the same
        # organization as the entry. NULL shift_id (unscheduled work, or
        # no single unambiguous shift matched) bypasses this entirely.
        ForeignKeyConstraint(
            ["shift_id", "organization_id"],
            ["shifts.id", "shifts.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["edited_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ended_after_started"),
        # Sanity cap (mirrors shifts' ends_at - starts_at <= interval '24
        # hours', confirmed rule A7), so an entry has the same hard
        # duration bound whether it represents planned or actual work —
        # without this, a colluding manager+employee could otherwise post
        # an arbitrarily long entry that flows straight into overtime/
        # labor-cost calculations.
        CheckConstraint(
            "ended_at IS NULL OR ended_at - started_at <= interval '24 hours'",
            name="duration_max_24_hours",
        ),
        # See the module docstring: 'needs_review' is treated the same as
        # 'open' here — neither has an end time yet, only 'closed' does.
        CheckConstraint(
            "(status IN ('open', 'needs_review')) = (ended_at IS NULL)",
            name="status_open_matches_ended_at_null",
        ),
        CheckConstraint("break_minutes >= 0", name="break_minutes_non_negative"),
        # A break cannot consume the entire (closed) entry's duration.
        # Still open/needs_review (ended_at NULL) has nothing to check yet.
        CheckConstraint(
            "ended_at IS NULL OR "
            "break_minutes * 60 < EXTRACT(EPOCH FROM (ended_at - started_at))",
            name="break_minutes_less_than_duration",
        ),
        CheckConstraint(
            "status IN ('open', 'closed', 'needs_review')", name="status_valid"
        ),
        CheckConstraint(
            "source IN ('web', 'manual', 'import')", name="source_valid"
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="location_fields_paired"),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="longitude_range",
        ),
        # An edit must always carry who/when/why together — never just one
        # or two of the three.
        CheckConstraint(
            "edited_by_user_id IS NULL OR "
            "(edited_at IS NOT NULL AND edit_reason IS NOT NULL)",
            name="edit_requires_edited_at_and_reason",
        ),
        # The actual duplicate-clock-in guarantee, enforced at the DB
        # level: an employee may have at most one open (no ``ended_at``)
        # entry at a time, regardless of application logic.
        Index(
            "uq_attendance_entries_employee_id_open",
            "employee_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        # No overlapping entries for the same employee, including an open
        # entry blocking any later one — an unbounded range still
        # intersects. Hand-written to match app.models.shift's
        # ex_shifts_employee_no_overlap pattern exactly.
        ExcludeConstraint(
            ("employee_id", "="),
            (func.tstzrange(column("started_at"), column("ended_at")), "&&"),
            name="ex_attendance_entries_employee_no_overlap",
            using="gist",
        ),
        Index(
            "ix_attendance_entries_employee_id_started_at",
            "employee_id",
            "started_at",
        ),
        Index(
            "ix_attendance_entries_organization_id_business_date",
            "organization_id",
            "business_date",
        ),
        Index("ix_attendance_entries_shift_id", "shift_id"),
        # Round B fix: working_hours.worked_seconds_for_day/_week filter
        # on employee_id + a business_date range + status, called in
        # tight per-day loops by cost/report calculations — neither
        # existing index (employee_id+started_at, organization_id+
        # business_date) matches that predicate shape.
        Index(
            "ix_attendance_entries_employee_id_business_date",
            "employee_id",
            "business_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shift_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    business_date: Mapped[object] = mapped_column(Date, nullable=False)
    break_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    edited_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    edited_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    edit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Captured only at the clock-in/out instant (never continuous
    # tracking, per the client's explicit constraint) and only ever read
    # when Organization.location_validation_mode requires it — see
    # app.services.attendance. NULL for every entry an organization with
    # location_validation_mode == NONE ever creates.
    latitude: Mapped[object | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[object | None] = mapped_column(Numeric(9, 6), nullable=True)

    def __repr__(self) -> str:
        return f"<AttendanceEntry id={self.id} status={self.status!r}>"
