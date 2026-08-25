"""Shared model base pieces: constraint naming convention and mixins.

The naming convention is applied to ``db.metadata`` here, before any
model module defines a table, so every constraint and index created by
Alembic autogeneration gets a predictable, greppable name.
"""

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db.metadata.naming_convention = NAMING_CONVENTION


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` timestamp columns.

    Timestamps are timezone-aware and set by the database server, so the
    values are consistent regardless of application server clock/timezone.
    """

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
