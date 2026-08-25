"""LeaveType model — a small per-organization catalog of leave categories.

Leave balances/accrual are explicitly out of scope for the MVP (confirmed
rule for this milestone) — this is purely a categorization/policy table
that ``LeaveRequest`` rows reference, not a ledger.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class LeaveType(TimestampMixin, db.Model):
    __tablename__ = "leave_types"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("organization_id", "code"),
        # Target for the composite FK from leave_requests.(leave_type_id,
        # organization_id) — same "child table needs the parent's
        # composite unique target" pattern already used for
        # departments/employees/shifts.
        UniqueConstraint("id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    # Whether approved leave of this type should be treated as an
    # availability conflict against shifts. Almost always true, but the
    # column exists so an org can model an edge case like "jury duty
    # acknowledged but still on-call" without blocking scheduling.
    blocks_scheduling: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )

    def __repr__(self) -> str:
        return f"<LeaveType id={self.id} code={self.code!r}>"
