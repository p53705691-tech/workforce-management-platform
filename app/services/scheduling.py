"""Scheduling service: business logic for shift creation and lifecycle.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, independent of whatever the route layer already
checked — same pattern as ``app.services.employees``. A shift's
``department_id`` authorization is always checked explicitly against
``scope``, not inferred solely from a read-scoped lookup, since read and
write authorization are separate concerns (see ``update_employee`` in
M2 for the precedent).
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import abort
from sqlalchemy.exc import IntegrityError

from app.auth.scope import AccessScope, get_scoped_or_404
from app.extensions import db
from app.models.department import Department
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.shift import Shift
from app.services import audit as audit_service
from app.services import availability
from app.services.errors import ValidationError

# A shift may only be edited directly (via update_shift) while still a
# draft. department_id is included because reassigning a shift to a
# different department is still a plain field edit; employee_id is
# deliberately excluded — assignment always goes through assign_employee
# so overlap-checking happens in exactly one place.
_UPDATABLE_FIELDS = {"department_id", "starts_at", "ends_at", "break_minutes", "notes"}

# Name of the DB's overlap-prevention exclusion constraint (see migration
# 0008_create_shifts). Matched against IntegrityError.orig.diag so a race
# that slips past the service's best-effort pre-check still surfaces as a
# clean ValidationError instead of a raw 500.
_OVERLAP_EXCLUSION_CONSTRAINT = "ex_shifts_employee_no_overlap"


def organization_timezone(scope: AccessScope) -> ZoneInfo:
    """The caller's organization timezone, for the route layer to render
    (and pre-fill edit forms with) local wall-clock times instead of the
    raw UTC-normalized values PostgreSQL returns for a ``timestamptz``.
    """
    organization = db.session.get(Organization, scope.organization_id)
    return ZoneInfo(organization.timezone)


def _localize(value: datetime, tz: ZoneInfo) -> datetime:
    """Interpret a naive ``value`` as wall-clock time in ``tz``.

    A plain HTML ``datetime-local`` input (the only date/time control the
    project's vanilla-JS frontend can rely on) has no concept of timezone
    at all, so a naive value arriving here is, by definition, local
    wall-clock time for the organization — it is localized accordingly
    rather than rejected. A value that already carries a timezone (e.g. a
    future API client sending real ISO 8601 with an offset) is trusted
    as-is and passed through unchanged.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value


def business_date_for(starts_at: datetime, tz: ZoneInfo) -> date:
    """The attribution date for a point in time (confirmed rule A1): the
    local date of ``starts_at`` in the organization's timezone, so an
    overnight shift/attendance entry is attributed entirely to its start
    date, not split across two days.

    Public (not module-private) because rule A1 applies identically to
    attendance entries (``app.services.attendance``), not just shifts —
    shared here rather than duplicated so the two domains can never drift
    apart on this rule.
    """
    return starts_at.astimezone(tz).date()


def _validate_department_for_write(scope: AccessScope, department_id: int) -> None:
    """Confirm ``department_id`` exists in scope and the caller may write to it.

    Unlike a lookup on an existing row, there is nothing here for
    ``get_scoped_or_404`` to scope a query against, so the manager
    department-membership check is done explicitly against ``scope``.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

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
    if scope.role == "manager" and department_id not in scope.department_ids:
        abort(403)


def _validate_employee_assignable(scope: AccessScope, employee_id: int) -> Employee:
    """Confirm ``employee_id`` may be assigned a shift by the caller.

    The employee must belong to the caller's organization (the DB's
    composite FK is the actual authority; this turns a cross-tenant id
    into a clean ``ValidationError`` instead of a raw ``IntegrityError``).
    A manager may only assign employees from departments they manage.

    Only ``active`` employees may be newly assigned to a shift — a
    terminated or inactive employee must never appear on a future
    schedule. This only guards *new* assignment: a shift already assigned
    to an employee before they left active status is left untouched, so
    historical schedules stay intact (see ``app.services.employees.
    terminate_employee``, which never touches existing shifts either).
    """
    employee = (
        db.session.query(Employee)
        .filter(
            Employee.id == employee_id,
            Employee.organization_id == scope.organization_id,
        )
        .first()
    )
    if employee is None:
        raise ValidationError(
            "Selected employee does not exist in this organization.",
            field="employee_id",
        )
    if scope.role == "manager" and employee.department_id not in scope.department_ids:
        raise ValidationError(
            "You may only assign employees in departments you manage.",
            field="employee_id",
        )
    if employee.employment_status != "active":
        raise ValidationError(
            "Only an active employee may be assigned a shift.",
            field="employee_id",
        )
    return employee


def _check_overlap(
    scope: AccessScope,
    employee_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_shift_id: int | None = None,
) -> None:
    """Friendly pre-check before hitting the DB's exclusion constraint.

    This is best-effort (not race-free under concurrent commits); the
    database's EXCLUDE constraint is the actual authority, enforced by
    ``_commit_or_raise_overlap`` regardless of what happens here.
    """
    overlapping = availability.shifts_overlapping(
        scope, employee_id, starts_at, ends_at, exclude_shift_id=exclude_shift_id
    )
    if overlapping:
        raise ValidationError(
            "This employee already has an overlapping shift.",
            field="employee_id",
        )


def _check_leave_conflict(
    scope: AccessScope, employee_id: int, starts_at: datetime, ends_at: datetime
) -> None:
    """Block scheduling an employee over their own already-approved leave.

    The mirror image of ``app.services.leave.approve_leave``'s own check
    (which blocks *approving* leave that overlaps a published shift) — see
    that function's docstring. Without this, only one direction of the
    shift/leave relationship was ever enforced: a manager could create,
    update, or (re)assign a shift squarely inside leave that had already
    been approved. Unlike ``_check_overlap``, there is no database
    constraint backing this up (leave and shifts are different tables),
    so this pre-check is the only enforcement point — best-effort against
    a concurrent write, same as everywhere else in this module, but not
    optional.
    """
    conflicting = availability.approved_leave_overlapping(
        scope, employee_id, starts_at, ends_at
    )
    if conflicting:
        raise ValidationError(
            "This employee has approved leave that overlaps this shift.",
            field="employee_id",
        )


def _commit_or_raise_overlap() -> None:
    """Commit the session, translating an overlap-constraint violation.

    Any other ``IntegrityError`` is re-raised unchanged for the caller
    (route layer) to handle.
    """
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        constraint_name = getattr(
            getattr(error.orig, "diag", None), "constraint_name", None
        )
        if constraint_name == _OVERLAP_EXCLUSION_CONSTRAINT:
            raise ValidationError(
                "This employee already has an overlapping shift.",
                field="employee_id",
            ) from error
        raise


def _get_shift_for_write(scope: AccessScope, shift_id: int) -> Shift:
    if scope.role not in ("admin", "manager"):
        abort(403)

    shift = get_scoped_or_404(Shift, shift_id, scope)
    if scope.role == "manager" and shift.department_id not in scope.department_ids:
        abort(403)
    return shift


def list_shifts(
    scope: AccessScope, start: date, end: date, department_id: int | None = None
) -> list[Shift]:
    """List shifts visible to ``scope`` with ``business_date`` in [start, end].

    Admin: every shift in the organization. Manager: only shifts in
    departments they manage. Employee: only their own published shifts —
    an unpublished draft is still subject to change and a cancelled shift
    is no longer relevant, so neither is shown on an employee's schedule.
    """
    if scope.role == "employee":
        if scope.employee_id is None:
            return []
        query = db.session.query(Shift).filter(
            Shift.organization_id == scope.organization_id,
            Shift.employee_id == scope.employee_id,
            Shift.business_date >= start,
            Shift.business_date <= end,
            Shift.status == "published",
        )
        return query.order_by(Shift.starts_at).all()

    query = db.session.query(Shift).filter(
        Shift.organization_id == scope.organization_id,
        Shift.business_date >= start,
        Shift.business_date <= end,
    )
    if scope.role == "manager":
        query = query.filter(Shift.department_id.in_(scope.department_ids))
    if department_id is not None:
        query = query.filter(Shift.department_id == department_id)
    return query.order_by(Shift.starts_at).all()


def create_shift(
    scope: AccessScope,
    department_id: int,
    starts_at: datetime,
    ends_at: datetime,
    break_minutes: int = 0,
    employee_id: int | None = None,
    notes: str | None = None,
) -> Shift:
    """Create a draft shift. Admin, or manager restricted to own departments."""
    _validate_department_for_write(scope, department_id)

    tz = organization_timezone(scope)
    starts_at = _localize(starts_at, tz)
    ends_at = _localize(ends_at, tz)

    if employee_id is not None:
        _validate_employee_assignable(scope, employee_id)
        _check_overlap(scope, employee_id, starts_at, ends_at)
        _check_leave_conflict(scope, employee_id, starts_at, ends_at)

    shift = Shift(
        organization_id=scope.organization_id,
        department_id=department_id,
        employee_id=employee_id,
        starts_at=starts_at,
        ends_at=ends_at,
        business_date=business_date_for(starts_at, tz),
        break_minutes=break_minutes,
        notes=notes,
        status="draft",
        created_by_user_id=scope.user_id,
    )
    db.session.add(shift)
    _commit_or_raise_overlap()
    return shift


def update_shift(scope: AccessScope, shift_id: int, **fields) -> Shift:
    """Update a draft shift's editable fields.

    Only allowed while ``status == 'draft'``: a published shift's employee
    is changed through ``assign_employee`` and its lifecycle through
    ``publish_shift`` / ``cancel_shift``, not through a silent field edit.
    """
    shift = _get_shift_for_write(scope, shift_id)

    if shift.status != "draft":
        raise ValidationError(
            "Only a draft shift can be edited directly; use assign, "
            "publish, or cancel instead."
        )

    unknown_fields = set(fields) - _UPDATABLE_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    if "department_id" in fields:
        _validate_department_for_write(scope, fields["department_id"])

    times_changed = "starts_at" in fields or "ends_at" in fields
    tz = organization_timezone(scope) if times_changed else None
    if times_changed:
        if "starts_at" in fields:
            fields["starts_at"] = _localize(fields["starts_at"], tz)
        if "ends_at" in fields:
            fields["ends_at"] = _localize(fields["ends_at"], tz)
        new_starts_at = fields.get("starts_at", shift.starts_at)
        new_ends_at = fields.get("ends_at", shift.ends_at)
        if shift.employee_id is not None:
            _check_overlap(
                scope,
                shift.employee_id,
                new_starts_at,
                new_ends_at,
                exclude_shift_id=shift.id,
            )
            _check_leave_conflict(scope, shift.employee_id, new_starts_at, new_ends_at)

    for field, value in fields.items():
        setattr(shift, field, value)

    if times_changed:
        shift.business_date = business_date_for(shift.starts_at, tz)

    _commit_or_raise_overlap()
    return shift


def assign_employee(scope: AccessScope, shift_id: int, employee_id: int) -> Shift:
    """Assign (or reassign) an employee to a shift.

    Unlike other field edits, reassignment is allowed on a published
    shift, not just a draft one — a shift's employee can legitimately
    change after publishing (e.g. covering a call-out), which is exactly
    why this is its own action instead of part of ``update_shift``.
    """
    shift = _get_shift_for_write(scope, shift_id)

    if shift.status == "cancelled":
        raise ValidationError("Cannot assign an employee to a cancelled shift.")

    _validate_employee_assignable(scope, employee_id)
    _check_overlap(
        scope, employee_id, shift.starts_at, shift.ends_at, exclude_shift_id=shift.id
    )
    _check_leave_conflict(scope, employee_id, shift.starts_at, shift.ends_at)

    shift.employee_id = employee_id
    _commit_or_raise_overlap()
    return shift


def publish_shift(scope: AccessScope, shift_id: int) -> Shift:
    """Publish a draft shift. Requires an assigned employee.

    An unassigned shift stays visible as an open, draft shift for
    coverage-planning purposes (see ``coverage_summary``); it cannot be
    published, since "published" means a committed, employee-facing
    schedule entry.
    """
    shift = _get_shift_for_write(scope, shift_id)

    if shift.status != "draft":
        raise ValidationError("Only a draft shift can be published.")
    if shift.employee_id is None:
        raise ValidationError("Cannot publish a shift with no employee assigned.")

    shift.status = "published"
    shift.published_at = datetime.now(timezone.utc)
    audit_service.record(
        "shift_published",
        "shift",
        entity_id=shift.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": shift.employee_id, "department_id": shift.department_id},
    )
    # One commit covers both the publish update and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()
    return shift


def cancel_shift(scope: AccessScope, shift_id: int) -> Shift:
    """Cancel a shift. Never deletes the row — history matters for reporting."""
    shift = _get_shift_for_write(scope, shift_id)

    if shift.status == "cancelled":
        raise ValidationError("Shift is already cancelled.")

    shift.status = "cancelled"
    # The DB's (status = 'published') = (published_at IS NOT NULL) CHECK
    # requires published_at to be NULL for every non-published status,
    # including cancelled, so a previously-published shift's publish
    # timestamp cannot be preserved here — only that the row itself
    # (and its start/end/employee) survives as cancelled, not deleted.
    shift.published_at = None
    audit_service.record(
        "shift_cancelled",
        "shift",
        entity_id=shift.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": shift.employee_id, "department_id": shift.department_id},
    )
    # One commit covers both the cancellation and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return shift


def coverage_summary(
    scope: AccessScope, department_id: int, business_date: date
) -> dict:
    """Published shifts vs. active employees for a department/day.

    Deliberately minimal: a single pair of counts, not a full staffing
    model. Good enough to start answering "do we have enough people
    scheduled" without over-building ahead of real requirements.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)
    if scope.role == "manager" and department_id not in scope.department_ids:
        abort(403)

    published_shift_count = (
        db.session.query(Shift)
        .filter(
            Shift.organization_id == scope.organization_id,
            Shift.department_id == department_id,
            Shift.business_date == business_date,
            Shift.status == "published",
        )
        .count()
    )
    active_employee_count = (
        db.session.query(Employee)
        .filter(
            Employee.organization_id == scope.organization_id,
            Employee.department_id == department_id,
            Employee.employment_status == "active",
        )
        .count()
    )
    return {
        "published_shifts": published_shift_count,
        "active_employees": active_employee_count,
    }
