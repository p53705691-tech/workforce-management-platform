"""Employee service: business logic for employee CRUD.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, independent of whatever the route layer already
checked (see ``update_employee`` in particular: read-scope and
write-authorization are checked separately on purpose).
"""

from datetime import date

from flask import abort

from app.auth.scope import AccessScope, get_scoped_or_404
from app.extensions import db
from app.models.department import Department
from app.models.employee import Employee
from app.services import audit as audit_service
from app.services.errors import ValidationError

_REQUIRED_CREATE_FIELDS = {
    "department_id",
    "employee_number",
    "first_name",
    "last_name",
    "employment_status",
    "hired_on",
}
_OPTIONAL_CREATE_FIELDS = {"email", "phone", "weekly_contract_hours"}
_CREATE_FIELDS = _REQUIRED_CREATE_FIELDS | _OPTIONAL_CREATE_FIELDS

# hired_on and terminated_on are deliberately excluded: hired_on isn't
# expected to change after the fact, and terminated_on may only be set
# together with employment_status via terminate_employee, which is the
# one place that can satisfy the DB's paired CHECK constraint atomically.
_UPDATABLE_FIELDS = {
    "department_id",
    "employee_number",
    "first_name",
    "last_name",
    "email",
    "phone",
    "employment_status",
    "weekly_contract_hours",
}


def _validate_department(scope: AccessScope, department_id: int) -> None:
    """Confirm ``department_id`` exists in the caller's organization.

    Defense in depth beyond the DB's composite FK: this turns a
    cross-organization department id into a clean ``ValidationError``
    instead of a raw ``IntegrityError`` bubbling out of a commit.
    """
    department = (
        db.session.query(Department)
        .filter(
            Department.id == department_id,
            Department.organization_id == scope.organization_id,
        )
        .first()
    )
    if department is None:
        raise ValidationError(
            "Selected department does not exist in this organization.",
            field="department_id",
        )


def list_employees(scope: AccessScope) -> list[Employee]:
    """List employees visible to ``scope``.

    Admin: every employee in the organization. Manager: only employees in
    departments they manage. Employee: only their own record.
    """
    if scope.role == "employee":
        if scope.employee_id is None:
            return []
        query = db.session.query(Employee).filter(
            Employee.id == scope.employee_id,
            Employee.organization_id == scope.organization_id,
        )
        return query.all()

    query = db.session.query(Employee).filter(
        Employee.organization_id == scope.organization_id
    )
    if scope.role == "manager":
        query = query.filter(Employee.department_id.in_(scope.department_ids))
    return query.order_by(Employee.last_name, Employee.first_name).all()


def get_employee(scope: AccessScope, employee_id: int) -> Employee:
    """Fetch a single employee, or 404 if out of ``scope``.

    ``get_scoped_or_404`` already restricts managers to their managed
    departments and everyone to their own organization. An employee-role
    caller is restricted further, explicitly, to their own record —
    ``get_scoped_or_404`` has no notion of "employee's own record" since
    that isn't keyed by ``department_id``.
    """
    if scope.role == "employee" and scope.employee_id != employee_id:
        abort(404)
    return get_scoped_or_404(Employee, employee_id, scope)


def create_employee(scope: AccessScope, **fields) -> Employee:
    """Create an employee in the caller's organization. Admin only."""
    if scope.role != "admin":
        abort(403)

    unknown_fields = set(fields) - _CREATE_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    missing_fields = _REQUIRED_CREATE_FIELDS - set(fields)
    if missing_fields:
        raise ValidationError(
            f"Missing required field(s): {', '.join(sorted(missing_fields))}"
        )

    _validate_department(scope, fields["department_id"])

    employee = Employee(organization_id=scope.organization_id, **fields)
    db.session.add(employee)
    db.session.commit()
    return employee


def update_employee(scope: AccessScope, employee_id: int, **fields) -> Employee:
    """Update an employee's editable fields.

    Admin may update any employee in their organization. A manager may
    only update employees in departments they manage — checked here
    explicitly rather than relying solely on the read-scoped lookup,
    since read and write authorization are separate concerns that could
    diverge later.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

    employee = get_scoped_or_404(Employee, employee_id, scope)

    if scope.role == "manager" and employee.department_id not in scope.department_ids:
        abort(403)

    unknown_fields = set(fields) - _UPDATABLE_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    if fields.get("employment_status") == "terminated":
        raise ValidationError(
            "Use the terminate action to set an employee's status to terminated.",
            field="employment_status",
        )

    if "department_id" in fields:
        target_department_id = fields["department_id"]
        _validate_department(scope, target_department_id)
        if (
            scope.role == "manager"
            and target_department_id not in scope.department_ids
        ):
            raise ValidationError(
                "You may only assign employees to departments you manage.",
                field="department_id",
            )

    for field, value in fields.items():
        setattr(employee, field, value)

    # changes records which fields changed, never their new values: some
    # updatable fields (email, phone, name) are PII, no less sensitive
    # than the pay-rate value app.services.pay_rates.set_pay_rate already
    # keeps out of its own audit entry — see app.services.audit's module
    # docstring on keeping changes small and non-sensitive.
    audit_service.record(
        "employee_updated",
        "employee",
        entity_id=employee.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": employee.id, "fields_changed": sorted(fields)},
    )
    # One commit covers both the update and the audit entry above — see
    # app.services.audit's module docstring.
    db.session.commit()
    return employee


def terminate_employee(scope: AccessScope, employee_id: int, terminated_on: date) -> Employee:
    """Terminate an employee. Admin only.

    Sets ``employment_status`` and ``terminated_on`` together in the same
    update so the DB's
    ``(employment_status = 'terminated') = (terminated_on IS NOT NULL)``
    CHECK constraint is always satisfied by the resulting row.
    """
    if scope.role != "admin":
        abort(403)

    employee = get_scoped_or_404(Employee, employee_id, scope)
    employee.employment_status = "terminated"
    employee.terminated_on = terminated_on

    # str(), not .isoformat(): terminated_on is typed as date, but at
    # least one existing caller passes a plain ISO string through
    # unchanged (relying on the DB column to coerce it) rather than a
    # date object, and str() gives the same ISO-8601 text either way.
    audit_service.record(
        "employee_terminated",
        "employee",
        entity_id=employee.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"terminated_on": str(terminated_on)},
    )
    # One commit covers both the termination update and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()
    return employee
