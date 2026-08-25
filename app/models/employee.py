"""Employee model.

Schema only for M1: ``users`` has a composite FK to this table, so it must
exist now with its ``(id, organization_id)`` uniqueness in place. The
service/route layer for employee management arrives in M2.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class Employee(TimestampMixin, db.Model):
    __tablename__ = "employees"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        # Composite FK: an employee's department must belong to the same
        # organization as the employee itself (cross-tenant guard).
        ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "employee_number"),
        # Target for the composite FK from users.(employee_id, organization_id).
        UniqueConstraint("id", "organization_id"),
        CheckConstraint("length(trim(first_name)) > 0", name="first_name_not_blank"),
        CheckConstraint("length(trim(last_name)) > 0", name="last_name_not_blank"),
        CheckConstraint(
            "employment_status IN ('active', 'inactive', 'terminated')",
            name="employment_status_valid",
        ),
        CheckConstraint("pay_type = 'hourly'", name="pay_type_hourly_only"),
        CheckConstraint(
            "weekly_contract_hours IS NULL OR "
            "(weekly_contract_hours >= 0 AND weekly_contract_hours <= 168)",
            name="weekly_contract_hours_range",
        ),
        CheckConstraint(
            "terminated_on IS NULL OR terminated_on >= hired_on",
            name="terminated_on_after_hired_on",
        ),
        CheckConstraint(
            "(employment_status = 'terminated') = (terminated_on IS NOT NULL)",
            name="terminated_status_matches_terminated_on",
        ),
        # Partial unique index: only enforce email uniqueness for rows that
        # actually have one (NULL emails must not collide with each other).
        Index(
            "uq_employees_organization_id_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        # Round B fix: Postgres does not auto-index FK columns, and
        # department-scoped employee queries are common (manager-scoped
        # employees.list_employees, scheduling.coverage_summary,
        # reports._department_employees) but had no index support beyond
        # a sequential scan over the organization's employees.
        Index(
            "ix_employees_organization_id_department_id",
            "organization_id",
            "department_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    department_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_number: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    employment_status: Mapped[str] = mapped_column(Text, nullable=False)
    pay_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="hourly"
    )
    weekly_contract_hours: Mapped[object | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    hired_on: Mapped[object] = mapped_column(Date, nullable=False)
    terminated_on: Mapped[object | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<Employee id={self.id} employee_number={self.employee_number!r}>"
