"""Organization model — the top-level tenant boundary.

Every other domain table is scoped to an organization. Multi-tenancy is
enforced both by required ``organization_id`` foreign keys on child tables
and by application-level authorization checks (see ``app.auth.scope``).
"""

from sqlalchemy import BigInteger, CHAR, Boolean, CheckConstraint, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class Organization(TimestampMixin, db.Model):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "char_length(currency_code) = 3", name="currency_code_length"
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

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r}>"
