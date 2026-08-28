"""Organization model — the top-level tenant boundary.

Every other domain table is scoped to an organization. Multi-tenancy is
enforced both by required ``organization_id`` foreign keys on child tables
and by application-level authorization checks (see ``app.auth.scope``).
"""

from sqlalchemy import BigInteger, CHAR, Boolean, CheckConstraint, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin



# Confirmed rule for this pass: clock-in/out location validation is
# entirely opt-in and configurable per organization, never a hardcoded
# assumption of a fixed office — a taxi business (mobile workers) must
# never be forced into a geofence, per the client's explicit constraint.
#
#   NONE               - no location check at all (default; e.g. taxi
#                         with no location feature enabled).
#   FIXED_SITE          - clock-in/out must be within the employee's own
#                          department's configured radius (e.g. a
#                          barbershop's fixed branches).
#   MULTI_SITE           - validated against whichever JobLocation the
#                          matched shift specifies, if any (multiple
#                          known sites, not tied to a department).
#   MOBILE               - never validated (taxi/field workers with no
#                          fixed or predictable location at all).
#   SHIFT_JOB_LOCATION   - same mechanism as MULTI_SITE (validated
#                          against the matched shift's job_location);
#                          kept as a distinct, separately named value
#                          per the client's spec rather than merged with
#                          MULTI_SITE, since the two describe different
#                          business intents (many interchangeable sites
#                          vs. a specific customer job per shift, e.g.
#                          cleaning) even though today's enforcement
#                          logic happens to be identical.
LOCATION_VALIDATION_MODES = (
    "NONE",
    "FIXED_SITE",
    "MULTI_SITE",
    "MOBILE",
    "SHIFT_JOB_LOCATION",
)


class Organization(TimestampMixin, db.Model):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "char_length(currency_code) = 3", name="currency_code_length"
        ),
        CheckConstraint(
            "location_validation_mode IN ('NONE', 'FIXED_SITE', 'MULTI_SITE', "
            "'MOBILE', 'SHIFT_JOB_LOCATION')",
            name="location_validation_mode_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    location_validation_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="NONE"
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r}>"
