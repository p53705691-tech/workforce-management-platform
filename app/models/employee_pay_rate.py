"""EmployeePayRate model — effective-dated hourly rate history.

Rate history, not a column on ``Employee`` (confirmed rule for this
milestone): a rate change must not silently rewrite the cost of
already-worked historical periods, so each rate is its own row with an
effective date range, mirroring the effective-dating convention already
used for ``OvertimePolicy`` — see that model's docstring for the general
shape (a NULL ``effective_to`` means "still in force").

Hourly rate only for MVP (confirmed rule): every employee has a Decimal
hourly rate. ``Employee.pay_type`` is currently constrained to
``'hourly'`` only (see ``app/models/employee.py``'s
``pay_type_hourly_only`` CHECK), so no salaried-employee handling exists
here or anywhere else in this milestone.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Numeric,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class EmployeePayRate(TimestampMixin, db.Model):
    __tablename__ = "employee_pay_rates"
    __table_args__ = (
        # Composite FK: the rate's employee must belong to the same
        # organization as the rate row itself (cross-tenant guard, same
        # pattern as shifts/attendance/leave requests).
        ForeignKeyConstraint(
            ["employee_id", "organization_id"],
            ["employees.id", "employees.organization_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("hourly_rate > 0", name="hourly_rate_positive"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_to_after_effective_from",
        ),
        # Effective-dated exclusivity: no two overlapping rate periods for
        # the same employee. Hand-written to match what
        # postgresql.ExcludeConstraint compiles to here (autogenerate
        # cannot produce this DDL) — see
        # migrations/versions/0012_create_employee_pay_rates.py, verified
        # against pg_constraint once applied. Mirrors
        # OvertimePolicy.ex_overtime_policies_organization_no_overlap
        # exactly, scoped to employee_id instead of organization_id.
        ExcludeConstraint(
            ("employee_id", "="),
            (
                func.daterange(
                    column("effective_from"), column("effective_to"), text("'[]'")
                ),
                "&&",
            ),
            name="ex_employee_pay_rates_employee_no_overlap",
            using="gist",
        ),
        Index(
            "ix_employee_pay_rates_employee_id_effective_from",
            "employee_id",
            "effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hourly_rate: Mapped[object] = mapped_column(Numeric(10, 4), nullable=False)
    effective_from: Mapped[object] = mapped_column(Date, nullable=False)
    effective_to: Mapped[object | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<EmployeePayRate id={self.id} employee_id={self.employee_id}>"
