"""Department model.

Schema only for M1: the ``users`` table has a composite FK down through
``employees`` to this table, so it must exist now with its
``(id, organization_id)`` uniqueness in place. The service/route layer for
department management arrives in M2.
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Text, UniqueConstraint, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class Department(TimestampMixin, db.Model):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        # Target for composite FKs from every child table (employees,
        # department_managers, ...): guarantees a referencing row's
        # organization_id always matches the department's own.
        UniqueConstraint("id", "organization_id"),
        # Case-insensitive uniqueness of department name per organization;
        # must be a functional index, not a plain UniqueConstraint.
        Index(
            "uq_departments_organization_id_lower_name",
            "organization_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )

    def __repr__(self) -> str:
        return f"<Department id={self.id} code={self.code!r}>"
