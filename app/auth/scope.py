"""Organizational access scope for authorization decisions.

``AccessScope`` captures what a signed-in user is allowed to see:

- Every role is confined to exactly one organization (``organization_id``).
- ``admin``: no further restriction beyond the organization (org-wide
  access), checked by role, not by scope membership.
- ``manager``: restricted to the departments they manage
  (``department_ids``), sourced from ``department_managers``.
- ``employee``: restricted to their own employee record
  (``employee_id``), checked by identity, not by department.
"""

from dataclasses import dataclass

from flask import abort

from app.extensions import db
from app.models.department_manager import DepartmentManager


@dataclass(frozen=True)
class AccessScope:
    user_id: int
    organization_id: int
    role: str
    department_ids: frozenset[int]
    employee_id: int | None


def build_scope_for_user(user) -> AccessScope:
    """Build the ``AccessScope`` for an authenticated ``User``."""
    department_ids: frozenset[int] = frozenset()

    if user.role == "manager":
        rows = (
            db.session.query(DepartmentManager.department_id)
            .filter(DepartmentManager.user_id == user.id)
            .all()
        )
        department_ids = frozenset(department_id for (department_id,) in rows)

    return AccessScope(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        department_ids=department_ids,
        employee_id=user.employee_id,
    )


def get_scoped_or_404(model, obj_id, scope: AccessScope):
    """Fetch a ``model`` row constrained to ``scope``, or abort with 404.

    Always filters by organization. Managers are additionally constrained
    to their managed departments when ``model`` has a ``department_id``
    column. This is the IDOR defense: routes must fetch tenant-owned rows
    through this helper rather than ``Model.query.get(id)``.

    A 404 (not 403) is returned for out-of-scope rows so a caller cannot
    distinguish "doesn't exist" from "exists but you can't see it".
    """
    query = db.session.query(model).filter(
        model.id == obj_id,
        model.organization_id == scope.organization_id,
    )

    if scope.role == "manager" and hasattr(model, "department_id"):
        query = query.filter(model.department_id.in_(scope.department_ids))

    obj = query.first()
    if obj is None:
        abort(404)
    return obj
