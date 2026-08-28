"""PasswordResetToken model — single-use, short-lived self-service reset.

Only the SHA-256 hash of the raw token is ever stored (mirrors never
storing a raw password — see ``app.auth.passwords``): the raw token
exists only in the reset-link URL emailed to the user, never persisted
anywhere. A token is single-use (``used_at``) and short-lived
(``expires_at``), both enforced in ``app.auth.service.reset_password``,
not by the database — there's no meaningful DB-level constraint for "is
this timestamp in the past," and single-use is enforced by checking
``used_at IS NULL`` before consuming, then setting it, all within the
one request that redeems the token (no concurrent-redemption race
matters here in practice: a second, near-simultaneous redemption attempt
with the same raw token just finds ``used_at`` already set and is
rejected as invalid, same as any other "already consumed" resource).
"""

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import TimestampMixin


class PasswordResetToken(TimestampMixin, db.Model):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_tokens_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # SHA-256 hex digest (64 chars) of the raw token — a fast hash is
    # appropriate here (unlike password hashing): the token itself
    # already carries 256 bits of ``secrets.token_urlsafe`` entropy, so
    # there's no offline brute-force risk to slow down, only a need for
    # a reliable, indexable lookup key.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PasswordResetToken id={self.id} user_id={self.user_id}>"
