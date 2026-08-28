"""Department model.

Schema only for M1: the ``users`` table has a composite FK down through
``employees`` to this table, so it must exist now with its
``(id, organization_id)`` uniqueness in place. The service/route layer for
department management arrives in M2.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
    true,
)
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
        # Fixed-site clock-in/out validation (Organization.location_
        # validation_mode == FIXED_SITE, e.g. a barbershop's branches) —
        # all three or none: a department is never "half configured"
        # for this, which would otherwise let a validation check run
        # against a missing radius or coordinate.
        CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL) AND "
            "(latitude IS NULL) = (radius_meters IS NULL)",
            name="location_fields_paired",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="longitude_range",
        ),
        CheckConstraint(
            "radius_meters IS NULL OR radius_meters > 0", name="radius_meters_positive"
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
    # Only meaningful when the organization's location_validation_mode is
    # FIXED_SITE — NULL otherwise (and NULL is exactly what a taxi/mobile
    # organization keeps them at, since nothing ever requires setting
    # these). See app.services.attendance's location-validation logic.
    latitude: Mapped[object | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[object | None] = mapped_column(Numeric(9, 6), nullable=True)
    radius_meters: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:
        return f"<Department id={self.id} code={self.code!r}>"
