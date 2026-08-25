"""Department-manager assignment.

A manager-role user's ``AccessScope`` (see ``app.auth.scope``) is derived
from these rows: which departments they are allowed to act within.
"""

from sqlalchemy import BigInteger, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class DepartmentManager(db.Model):
    __tablename__ = "department_managers"
    __table_args__ = (
        # Composite FK: the managed department must belong to the same
        # organization recorded on this row. Explicit RESTRICT for
        # consistency with every other composite FK in the schema (this
        # one previously had no explicit ondelete, defaulting to NO
        # ACTION — functionally similar but inconsistent).
        ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            ondelete="RESTRICT",
        ),
        # Round B fix: previously a plain FK to users.id with nothing
        # asserting the manager's own organization_id matched this row's
        # — the application happened to fail closed anyway (every scoped
        # query independently filters by organization), but the
        # invariant belongs in the database, per this project's own
        # database rule, not solely in every future query remembering to
        # filter correctly. Requires users.uq_users_id (id,
        # organization_id) as the composite target.
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    department_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<DepartmentManager user_id={self.user_id} "
            f"department_id={self.department_id}>"
        )
