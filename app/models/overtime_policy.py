"""OvertimePolicy model — the effective-dated overtime rules for an org.

Thresholds and multipliers are configurable data, never hardcoded
constants (confirmed rule for this milestone): a policy row carries the
daily/weekly thresholds and ``week_start_day``, while the actual
multiplier tiers live in the child ``OvertimeTier`` rows (see
``app/models/overtime_tier.py``).

Effective-dating mirrors the "one row covers a span of time" convention
already used for shifts/attendance, but at the policy level instead of
the individual-shift level: at most one policy may be in force for a
given organization on any given calendar day. That is enforced here with
a GiST exclusion constraint over ``daterange(effective_from,
effective_to, '[]')`` — a NULL ``effective_to`` means "still in force",
which ``daterange`` treats as an unbounded upper edge regardless of the
``'[]'`` bounds flag on that side.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
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


class OvertimePolicy(TimestampMixin, db.Model):
    __tablename__ = "overtime_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(
            "daily_threshold_hours > 0 AND daily_threshold_hours <= 24",
            name="daily_threshold_hours_range",
        ),
        CheckConstraint(
            "weekly_threshold_hours > 0 AND weekly_threshold_hours <= 168",
            name="weekly_threshold_hours_range",
        ),
        CheckConstraint(
            "week_start_day BETWEEN 0 AND 6", name="week_start_day_range"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_to_after_effective_from",
        ),
        # Effective-dated exclusivity: exactly one policy in force per
        # organization per day. Hand-written to match what
        # postgresql.ExcludeConstraint compiles to here (autogenerate
        # cannot produce this DDL) — see
        # migrations/versions/0010_create_overtime_policies_and_tiers.py,
        # verified against pg_constraint once applied.
        ExcludeConstraint(
            ("organization_id", "="),
            (
                func.daterange(
                    column("effective_from"), column("effective_to"), text("'[]'")
                ),
                "&&",
            ),
            name="ex_overtime_policies_organization_no_overlap",
            using="gist",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    daily_threshold_hours: Mapped[object] = mapped_column(Numeric(5, 2), nullable=False)
    weekly_threshold_hours: Mapped[object] = mapped_column(Numeric(5, 2), nullable=False)
    week_start_day: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    effective_from: Mapped[object] = mapped_column(Date, nullable=False)
    effective_to: Mapped[object | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<OvertimePolicy id={self.id} name={self.name!r}>"
