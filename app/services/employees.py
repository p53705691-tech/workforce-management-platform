"""Employee service: business logic for employee CRUD.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, independent of whatever the route layer already
checked (see ``update_employee`` in particular: read-scope and
write-authorization are checked separately on purpose).

Notification foundation fix — ``create_employee_account`` and
``reset_employee_account_password`` each send a best-effort email
through ``app.services.notifications.send_email`` strictly *after*
their own commit already succeeded (see that module's docstring). The
email never carries the password itself, new or otherwise; the
password stays out-of-band, delivered by whoever created/reset the
account.
"""

from datetime import date, datetime, timezone

from flask import abort
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import hash_password
from app.auth.scope import AccessScope, get_scoped_or_404
from app.extensions import db
from app.models.department import Department
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.user import User
from app.services import audit as audit_service
from app.services import notifications as notification_service
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


def _validate_department(
    scope: AccessScope, department_id: int, require_active: bool = False
) -> None:
    """Confirm ``department_id`` exists in the caller's organization.

    Defense in depth beyond the DB's composite FK: this turns a
    cross-organization department id into a clean ``ValidationError``
    instead of a raw ``IntegrityError`` bubbling out of a commit.

    ``require_active`` additionally rejects a deactivated department —
    used only when an employee is newly being placed there (creation, or
    a genuine reassignment away from their current department in
    ``update_employee``), never for an unrelated edit that happens to
    resubmit an employee's *existing*, already-inactive department
    unchanged. Deactivation is meant to retire a department going
    forward while leaving its existing history (and the employees
    already in it) untouched, not to block every future edit to them.
    """
    department = (
        db.session.query(Department)
        .filter(
            Department.id == department_id,
            Department.organization_id == scope.organization_id,
        )
        .first()
    )
    if department is None or (require_active and not department.is_active):
        raise ValidationError(
            "Selected department does not exist in this organization.",
            field="department_id",
        )


def _notify_employee_account_email(
    scope: AccessScope, employee: Employee, user: User, template_name: str, subject: str
) -> None:
    """Best-effort notification to ``employee`` about their login
    account (creation or an admin-driven password reset). Silently does
    nothing if the employee has no email on file (``Employee.email`` is
    nullable) — the same "skip, don't error" precedent used everywhere
    else a notification depends on optional contact info (see
    ``app.services.leave``'s equivalent helpers).

    Never includes the password itself, new or otherwise — see
    ``app.services.audit``'s module docstring on never dumping a
    sensitive value, applied the same way here. The email only confirms
    the account/login email; the actual password is delivered
    out-of-band by whoever created/reset it.

    Only ever called after the caller's own commit has already
    succeeded — see ``app.services.notifications``'s module docstring.
    """
    if not employee.email:
        return

    organization = db.session.get(Organization, scope.organization_id)
    notification_service.send_email(
        employee.email,
        subject,
        template_name,
        organization_name=organization.name,
        login_email=user.email,
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


def get_linked_user(scope: AccessScope, employee_id: int) -> User | None:
    """The login account linked to this employee, if any (``users.
    employee_id`` is unique, so at most one). Callable only after
    ``get_employee`` has already confirmed ``employee_id`` is visible to
    ``scope`` — this does no scoping of its own beyond the organization
    match, same "caller already resolved the parent record" precedent as
    ``pay_rates.list_pay_rate_history``.

    An employee with no linked account (e.g. added to the roster before
    their login was created) is a normal, expected state, not an error.
    """
    return (
        db.session.query(User)
        .filter(User.organization_id == scope.organization_id, User.employee_id == employee_id)
        .first()
    )


def create_employee_account(
    scope: AccessScope, employee_id: int, email: str, password: str
) -> User:
    """Create the login account for an existing employee. Admin only.

    There is no self-service sign-up route anywhere in this codebase —
    the confirmed workflow is "admin/manager creates the Employee record,
    then the employee logs in" (see MVP-1_version2.md's Account and
    Employee Model section), but until this function existed there was
    no way to actually create the ``User`` row that step depends on.
    Reuses the existing ``User`` model, its role/organization
    constraints, and the existing Argon2 hashing — this is not a second
    authentication system, just the missing write path for the first
    one.

    Always creates an ``employee``-role account linked to
    ``employee_id`` — this function is not a general "create any user"
    tool (admin/manager account provisioning is a separate, unaddressed
    concern outside this workflow).

    After the account is committed, the employee is notified by email
    (best-effort — see ``app.services.notifications``) that their
    account is ready; the email never includes the password itself
    (see ``_notify_employee_account_email``). Silently does nothing if
    the employee has no email on file.
    """
    if scope.role != "admin":
        abort(403)

    employee = get_employee(scope, employee_id)

    existing = (
        db.session.query(User).filter(User.employee_id == employee.id).first()
    )
    if existing is not None:
        raise ValidationError("This employee already has a login account.")

    user = User(
        organization_id=scope.organization_id,
        employee_id=employee.id,
        email=email,
        password_hash=hash_password(password),
        role="employee",
        is_active=True,
    )
    db.session.add(user)
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        raise ValidationError(
            "This email address is already in use.", field="email"
        ) from error

    # changes excludes the password entirely (see app.services.audit's
    # module docstring: never a raw dump of a sensitive value).
    audit_service.record(
        "employee_account_created",
        "user",
        entity_id=user.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": employee.id},
    )
    # One commit covers both the account creation and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()

    # Deliberately after the commit above — see
    # app.services.notifications's module docstring.
    _notify_employee_account_email(
        scope, employee, user, "account_created", "Your account is ready"
    )
    return user


def reset_employee_account_password(
    scope: AccessScope, employee_id: int, new_password: str
) -> User:
    """Admin-only: reset an existing login account's password directly.

    An admin setting a new password directly — the employee then signs
    in with it and may change it themselves via
    ``auth.service.change_password`` — reuses the same trust model
    already established by ``create_employee_account``. This remains
    the right tool for an admin acting on an employee's behalf even now
    that ``app.services.notifications`` exists (see below): a
    self-service "email me a reset link" flow is a separate,
    not-yet-built feature (it needs its own token model and route), not
    something this function does.

    Also clears any lockout, so this doubles as the recovery path for
    an account locked out by repeated failed attempts, not only a
    forgotten password.

    After the reset is committed, the employee is notified by email
    (best-effort — see ``app.services.notifications``) that their
    password was reset by an admin; the email never includes the new
    password itself (see ``_notify_employee_account_email``). Silently
    does nothing if the employee has no email on file.
    """
    if scope.role != "admin":
        abort(403)

    employee = get_employee(scope, employee_id)
    user = (
        db.session.query(User).filter(User.employee_id == employee.id).first()
    )
    if user is None:
        raise ValidationError("This employee has no login account to reset.")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.failed_login_count = 0
    user.locked_until = None

    # changes excludes the password entirely (see app.services.audit's
    # module docstring: never a raw dump of a sensitive value).
    audit_service.record(
        "employee_account_password_reset",
        "user",
        entity_id=user.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": employee.id},
    )
    # One commit covers both the reset and the audit entry above — see
    # app.services.audit's module docstring.
    db.session.commit()

    # Deliberately after the commit above — see
    # app.services.notifications's module docstring.
    _notify_employee_account_email(
        scope, employee, user, "account_password_reset", "Your password was reset"
    )
    return user


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

    _validate_department(scope, fields["department_id"], require_active=True)

    employee = Employee(organization_id=scope.organization_id, **fields)
    db.session.add(employee)
    db.session.flush()
    audit_service.record(
        "employee_created",
        "employee",
        entity_id=employee.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": employee.id, "department_id": employee.department_id},
    )
    # One commit covers both the creation and the audit entry above —
    # see app.services.audit's module docstring.
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
        is_reassignment = target_department_id != employee.department_id
        _validate_department(
            scope, target_department_id, require_active=is_reassignment
        )
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


def update_own_contact_info(scope: AccessScope, phone: str | None) -> Employee:
    """Self-service: an employee updates their own phone number.

    The only field an employee may change about their own Employee
    record — every company-controlled field (department, employment
    status, hired_on, ...) stays reachable only through
    ``update_employee`` (admin/manager). Not routed through
    ``update_employee`` itself: that function's authorization is
    "admin, or manager within scope," which would let a manager reach
    this by accident; self-service needs its own, separate check.
    """
    if scope.role != "employee" or scope.employee_id is None:
        abort(403)

    employee = get_scoped_or_404(Employee, scope.employee_id, scope)
    employee.phone = phone

    audit_service.record(
        "employee_contact_info_updated",
        "employee",
        entity_id=employee.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": employee.id, "fields_changed": ["phone"]},
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

    Also deactivates the employee's linked login account (``User.
    is_active = False``), if one exists. Termination has no reverse path
    through this application (``update_employee`` refuses to move
    ``employment_status`` away from ``'terminated'`` — the DB's paired
    CHECK constraint above would reject it without also clearing
    ``terminated_on``, which is not an updatable field), so this is a
    one-way access revocation, not a suspension. ``load_user`` already
    treats ``is_active = False`` as "sign this session out on its very
    next request" (see that function's docstring), so a terminated
    employee's existing session stops working immediately, not just at
    their next login attempt.
    """
    if scope.role != "admin":
        abort(403)

    employee = get_scoped_or_404(Employee, employee_id, scope)

    # Compared as ISO-format strings, not date objects: see this
    # function's audit_service.record call below for why terminated_on
    # itself is not reliably a date object here (at least one existing
    # caller passes a plain ISO string through unchanged), and str() of
    # a date object is that same ISO format either way.
    if str(terminated_on) < str(employee.hired_on):
        raise ValidationError(
            "Termination date cannot be before the hire date.",
            field="terminated_on",
        )

    employee.employment_status = "terminated"
    employee.terminated_on = terminated_on

    linked_user = (
        db.session.query(User).filter(User.employee_id == employee.id).first()
    )
    if linked_user is not None:
        linked_user.is_active = False

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
