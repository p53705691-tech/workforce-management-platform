"""AuditLog model — an append-only record of privileged/sensitive actions.

Written only through ``app.services.audit.record``; no route or service
in this codebase ever updates or deletes a row here (see that module's
docstring) — that is what "append-only" means in practice, since
PostgreSQL itself doesn't enforce it at the table level.

``changes`` is deliberately a small, non-sensitive summary of what
happened, never a raw dump of a sensitive value (e.g. a password hash or
an hourly pay rate) — audit logs may be read more broadly within an
organization than the feature they describe, so a pay-rate change is
recorded as "a rate was set, by whom, for whom, effective when", never
the rate value itself (see ``app.services.pay_rates.set_pay_rate``).

``organization_id``/``actor_user_id`` are both nullable: a failed login
for an email that doesn't exist establishes no organization or user
context at all, and a wrong-password/locked-account failure has no
*authenticated* actor even when the organization is already known from
the matched account.
"""

from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, Index, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        Index(
            "ix_audit_logs_organization_id_entity_type_entity_id",
            "organization_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_audit_logs_actor_user_id_created_at", "actor_user_id", "created_at"
        ),
        # Round C fix: the only query against this table
        # (app.services.audit.list_entries) filters on
        # (organization_id, created_at range) and orders by
        # created_at DESC. Neither existing index serves that access
        # pattern, and this table grows without bound.
        Index(
            "ix_audit_logs_organization_id_created_at",
            "organization_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    # No TimestampMixin here on purpose: this table is append-only by
    # convention (no route ever updates a row), so there is deliberately
    # no updated_at column to invite one.
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r}>"
