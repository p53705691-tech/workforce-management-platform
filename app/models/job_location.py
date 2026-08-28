"""JobLocation model — a named site an organization's shifts can be
pinned to, for the MULTI_SITE / SHIFT_JOB_LOCATION clock-in validation
modes (see app.models.organization's module docstring for the full
enum). Distinct from Department: a cleaning company's customer sites
(or a taxi/multi-branch business's many locations) are not
organizational departments, just places work happens — modeling them as
a separate table keeps "who manages this work" (Department) and "where
this work happens" (JobLocation) independent, which is exactly what
lets a single shift be reassigned to a different site without touching
department structure.
"""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class JobLocation(TimestampMixin, db.Model):
    __tablename__ = "job_locations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        # Target for the composite FK from shifts.(job_location_id, organization_id).
        UniqueConstraint("id", "organization_id"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        CheckConstraint("radius_meters > 0", name="radius_meters_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[object] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[object] = mapped_column(Numeric(9, 6), nullable=False)
    radius_meters: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:
        return f"<JobLocation id={self.id} name={self.name!r}>"
