"""OvertimeTier model — the multiplier tiers belonging to an OvertimePolicy.

A tier is owned entirely by its policy and has no independent meaning
(``ON DELETE CASCADE``, unlike every RESTRICT-only FK elsewhere in the
schema — see ``database.md``'s "avoid accidental cascade deletes": this
is a deliberate exception because a tier genuinely cannot outlive its
policy).

``from_hours``/``to_hours`` are hours *beyond the policy's threshold* for
``scope`` (daily or weekly), not absolute worked hours — e.g. the tier
``(daily, from=0, to=2, multiplier=1.5)`` covers the first two hours past
the daily threshold, not the first two hours of the day.

No ``TimestampMixin`` here (unlike ``OvertimePolicy``): the milestone
spec lists timestamps for the policy but not for its tiers, and a tier
row's own history is meaningless once cascade-deleted with its policy —
recreate the policy's tiers instead of tracking edits to child rows.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class OvertimeTier(db.Model):
    __tablename__ = "overtime_tiers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["policy_id"], ["overtime_policies.id"], ondelete="CASCADE"
        ),
        CheckConstraint("scope IN ('daily', 'weekly')", name="scope_valid"),
        CheckConstraint("tier_order >= 0", name="tier_order_non_negative"),
        CheckConstraint("from_hours >= 0", name="from_hours_non_negative"),
        CheckConstraint("multiplier > 0", name="multiplier_positive"),
        CheckConstraint(
            "to_hours IS NULL OR to_hours > from_hours",
            name="to_hours_after_from_hours",
        ),
        # Explicit (not convention-derived) names: both constraints share
        # policy_id as their first column, and the project's "uq" naming
        # convention template keys only on column_0_name — leaving these
        # unnamed would make both compile to the same implicit name.
        UniqueConstraint(
            "policy_id", "scope", "tier_order",
            name="uq_overtime_tiers_policy_id_scope_tier_order",
        ),
        UniqueConstraint(
            "policy_id", "scope", "from_hours",
            name="uq_overtime_tiers_policy_id_scope_from_hours",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    policy_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    tier_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    from_hours: Mapped[object] = mapped_column(Numeric(5, 2), nullable=False)
    to_hours: Mapped[object | None] = mapped_column(Numeric(5, 2), nullable=True)
    multiplier: Mapped[object] = mapped_column(Numeric(4, 2), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<OvertimeTier id={self.id} scope={self.scope!r} "
            f"tier_order={self.tier_order}>"
        )
