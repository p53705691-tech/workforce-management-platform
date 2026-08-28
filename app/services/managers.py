"""Manager account service: admin-only creation of manager-role login
accounts and department-manager assignment.

This was the one account-provisioning workflow this codebase left
unaddressed until now — see
``app.services.employees.create_employee_account``'s docstring ("admin/
manager account provisioning is a separate, unaddressed concern outside
this workflow"). A manager account is a ``User``, not necessarily tied
to an ``Employee`` record (see ``app.models.department_manager``'s
module docstring and ``app.auth.scope`` — "Admin and manager users may
exist without a linked employee record"): it's purely an access grant.
If a manager is also HR-tracked staff, their ``Employee`` record is
created separately via ``app.services.employees``, same as any other
employee.
"""

from flask import abort
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import hash_password
from app.auth.scope import AccessScope, get_scoped_or_404
from app.extensions import db
from app.models.department import Department
from app.models.department_manager import DepartmentManager
from app.models.user import User
from app.services import audit as audit_service
from app.services.errors import ValidationError


def list_managers(scope: AccessScope) -> list[User]:
    """Every manager-role user in the caller's organization. Admin only."""
    if scope.role != "admin":
        abort(403)
    return (
        db.session.query(User)
        .filter(User.organization_id == scope.organization_id, User.role == "manager")
        .order_by(User.email)
        .all()
    )


def managed_department_ids(scope: AccessScope, user_id: int) -> set[int]:
    """The department ids a given manager currently manages. Admin only."""
    if scope.role != "admin":
        abort(403)
    rows = (
        db.session.query(DepartmentManager.department_id)
        .filter(
            DepartmentManager.organization_id == scope.organization_id,
            DepartmentManager.user_id == user_id,
        )
        .all()
    )
    return {row[0] for row in rows}


def create_manager_account(scope: AccessScope, email: str, password: str) -> User:
    """Create a new manager-role login. Admin only.

    Not linked to an Employee record — see module docstring. Newly
    created with no department assignments; the caller must grant at
    least one via ``assign_department`` for the account to be able to
    see or act on anything (an unassigned manager's ``AccessScope`` has
    an empty ``department_ids``, which every department-scoped query
    already treats as "nothing visible", not an error).
    """
    if scope.role != "admin":
        abort(403)

    user = User(
        organization_id=scope.organization_id,
        employee_id=None,
        email=email,
        password_hash=hash_password(password),
        role="manager",
        is_active=True,
    )
    db.session.add(user)
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        raise ValidationError("This email is already in use.", field="email") from error

    audit_service.record(
        "manager_account_created",
        "user",
        entity_id=user.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"email": email},
    )
    # One commit covers both the account creation and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()
    return user


def _get_manager_for_scope(scope: AccessScope, user_id: int) -> User:
    manager = (
        db.session.query(User)
        .filter(
            User.id == user_id,
            User.organization_id == scope.organization_id,
            User.role == "manager",
        )
        .first()
    )
    if manager is None:
        raise ValidationError(
            "Selected manager does not exist in this organization.", field="user_id"
        )
    return manager


def assign_department(scope: AccessScope, user_id: int, department_id: int) -> DepartmentManager:
    """Grant a manager access to one department. Admin only.

    Idempotent — assigning an already-managed department returns the
    existing row rather than raising, so a caller never has to check
    first.
    """
    if scope.role != "admin":
        abort(403)

    _get_manager_for_scope(scope, user_id)
    department = get_scoped_or_404(Department, department_id, scope)

    existing = (
        db.session.query(DepartmentManager)
        .filter(
            DepartmentManager.user_id == user_id,
            DepartmentManager.department_id == department.id,
        )
        .first()
    )
    if existing is not None:
        return existing

    assignment = DepartmentManager(
        user_id=user_id, department_id=department.id, organization_id=scope.organization_id
    )
    db.session.add(assignment)
    db.session.flush()
    audit_service.record(
        "department_manager_assigned",
        "department_manager",
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"user_id": user_id, "department_id": department.id},
    )
    # One commit covers both the assignment and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return assignment


def unassign_department(scope: AccessScope, user_id: int, department_id: int) -> None:
    """Revoke a manager's access to one department. Admin only.
    Silently does nothing if the manager didn't manage it — removing an
    already-absent assignment is not an error.
    """
    if scope.role != "admin":
        abort(403)

    assignment = (
        db.session.query(DepartmentManager)
        .filter(
            DepartmentManager.user_id == user_id,
            DepartmentManager.department_id == department_id,
            DepartmentManager.organization_id == scope.organization_id,
        )
        .first()
    )
    if assignment is None:
        return

    db.session.delete(assignment)
    audit_service.record(
        "department_manager_unassigned",
        "department_manager",
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"user_id": user_id, "department_id": department_id},
    )
    # One commit covers both the removal and the audit entry above — see
    # app.services.audit's module docstring.
    db.session.commit()
