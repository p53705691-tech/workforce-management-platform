"""Department service: business logic for department CRUD.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself — a route mistake elsewhere (a missing
``role_required``, a copy-pasted decorator) can never bypass tenant or
role boundaries as long as callers go through this module.
"""

from flask import abort

from app.auth.scope import AccessScope, get_scoped_or_404
from app.extensions import db
from app.models.department import Department
from app.services import audit as audit_service
from app.services.errors import ValidationError

# name/code are the only fields a caller may change through the generic
# update; is_active has its own dedicated action (deactivate_department)
# so that state transition stays a single, auditable code path.
_UPDATABLE_FIELDS = {"name", "code"}


def list_departments(scope: AccessScope) -> list[Department]:
    """List departments visible to ``scope``.

    Admins see every department in their organization. Managers see only
    the departments they manage. Employees are not expected to call this
    (routes restrict the list route to admin/manager), but the query is
    still organization-scoped defensively regardless of role.
    """
    query = db.session.query(Department).filter(
        Department.organization_id == scope.organization_id
    )
    if scope.role == "manager":
        query = query.filter(Department.id.in_(scope.department_ids))
    return query.order_by(Department.name).all()


def create_department(scope: AccessScope, name: str, code: str) -> Department:
    """Create a department in the caller's organization. Admin only."""
    if scope.role != "admin":
        abort(403)

    department = Department(
        organization_id=scope.organization_id,
        name=name,
        code=code,
    )
    db.session.add(department)
    db.session.commit()
    return department


def update_department(scope: AccessScope, department_id: int, **fields) -> Department:
    """Update an existing department's editable fields. Admin only.

    Admins have org-wide access, so the department lookup only needs to
    be organization-scoped. ``get_scoped_or_404`` only adds a
    department-id filter for managers, so calling it here is a no-op
    restriction for admins beyond the organization check.
    """
    if scope.role != "admin":
        abort(403)

    department = get_scoped_or_404(Department, department_id, scope)

    unknown_fields = set(fields) - _UPDATABLE_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    for field, value in fields.items():
        setattr(department, field, value)

    db.session.commit()
    return department


def deactivate_department(scope: AccessScope, department_id: int) -> Department:
    """Soft-deactivate a department. Admin only.

    Never deletes the row: employees and historical records (schedules,
    attendance, cost reports in later milestones) may still reference it.
    """
    if scope.role != "admin":
        abort(403)

    department = get_scoped_or_404(Department, department_id, scope)
    department.is_active = False
    audit_service.record(
        "department_deactivated",
        "department",
        entity_id=department.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
    )
    # One commit covers both the deactivation and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return department
