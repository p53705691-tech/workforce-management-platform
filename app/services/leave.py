"""Leave service: business logic for leave requests and their approval.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, independent of whatever the route layer already
checked — same pattern as ``app.services.scheduling``/``attendance``.

Leave balances/accrual are not tracked in the MVP (confirmed rule for this
milestone): this module only manages a request's lifecycle
(pending -> approved/rejected/cancelled), never a "days remaining"
concept.

Ambiguities resolved during implementation (see the confirmed source of
truth precedence in CLAUDE.md — explicit requirements over invented
behavior):

- ``request_leave``'s ``employee_id`` parameter is written in the spec
  without a default, but the same section also says it must support
  "self-service (employee requests own leave)" using "the same
  authorization pattern as ``attendance.clock_in``'s on-behalf-of logic",
  and ``clock_in``'s ``employee_id`` defaults to ``None`` (meaning "the
  caller's own record"). Mirroring the referenced pattern's actual
  behavior takes precedence over the literal parameter list, so
  ``employee_id`` defaults to ``None`` here too.
- The spec does not say whether a leave type's ``requires_approval``
  flag should cause auto-approval at creation. ``request_leave`` always
  creates ``status='pending'`` regardless of that flag, exactly as
  stated for the create step; ``requires_approval`` is left as
  policy/catalog data for a later milestone to act on rather than
  inventing auto-approval behavior now.
- The spec doesn't say which exception type the self-approval guard in
  ``approve_leave`` should raise. It is an instance-specific business
  rule (whether *this* request's employee happens to match the caller),
  not a blanket role restriction, so it follows the same precedent as
  ``app.services.scheduling._validate_employee_assignable`` (a manager
  acting on an employee outside their managed departments) and raises
  ``ValidationError`` rather than aborting with 403.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import abort
from sqlalchemy.exc import IntegrityError

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.services import audit as audit_service
from app.services import availability
from app.services.errors import ValidationError
from app.services.scheduling import organization_timezone

# Name of the DB's overlap-prevention exclusion constraint (see migration
# 0011_create_leave_types_and_requests). Matched against
# IntegrityError.orig.diag so a race that slips past the service's
# best-effort pre-check still surfaces as a clean ValidationError instead
# of a raw 500 — same pattern as app.services.scheduling's overlap
# handling.
_OVERLAP_EXCLUSION_CONSTRAINT = "ex_leave_requests_employee_no_overlap"

_DECIDABLE_ROLES = ("admin", "manager")


def _localize(value: datetime, tz: ZoneInfo) -> datetime:
    """Interpret a naive ``value`` as wall-clock time in ``tz``.

    Mirrors ``app.services.scheduling._localize`` exactly (see that
    function's docstring for the rationale) — duplicated rather than
    imported since it's a private, per-module adapter, not a shared
    business rule, same convention already used by
    ``app.services.attendance``.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value


def _validate_employee_for_scope(scope: AccessScope, employee_id: int) -> Employee:
    """Confirm ``employee_id`` may be acted on (requested for, approved,
    rejected, cancelled) by the caller.

    The employee must belong to the caller's organization (the DB's
    composite FK is the actual authority; this turns a cross-tenant id
    into a clean ``ValidationError`` instead of a raw ``IntegrityError``).
    A manager may only act on employees in departments they manage.

    Only called by ``request_leave`` (creating a *new* request) — the
    decision/cancellation paths fetch an existing request via
    ``_get_leave_request_for_scope`` instead, so a request already on the
    books for an employee later terminated is left alone; only a brand-
    new request is blocked, same "block new, not historical" rule as
    ``app.services.scheduling._validate_employee_assignable``.
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
            "You may only act on employees in departments you manage.",
            field="employee_id",
        )
    if employee.employment_status != "active":
        raise ValidationError(
            "Only an active employee may request leave.",
            field="employee_id",
        )
    return employee


def _validate_leave_type(scope: AccessScope, leave_type_id: int) -> LeaveType:
    leave_type = (
        db.session.query(LeaveType)
        .filter(
            LeaveType.id == leave_type_id,
            LeaveType.organization_id == scope.organization_id,
        )
        .first()
    )
    if leave_type is None:
        raise ValidationError(
            "Selected leave type does not exist in this organization.",
            field="leave_type_id",
        )
    return leave_type


def _get_leave_request_for_scope(scope: AccessScope, leave_request_id: int) -> LeaveRequest:
    """Fetch a leave request constrained to ``scope``, or 404.

    ``LeaveRequest`` has no ``department_id`` column of its own (unlike
    ``Shift``), so ``app.auth.scope.get_scoped_or_404``'s manager
    restriction doesn't apply automatically — the department check is
    done here via a join to the owning employee instead, same pattern as
    ``app.services.attendance._get_entry_for_scope``. A 404 (not 403) is
    returned for an out-of-scope request, same IDOR defense used
    everywhere else in the project.
    """
    leave_request = (
        db.session.query(LeaveRequest)
        .filter(
            LeaveRequest.id == leave_request_id,
            LeaveRequest.organization_id == scope.organization_id,
        )
        .first()
    )
    if leave_request is None:
        abort(404)

    if scope.role == "employee":
        if leave_request.employee_id != scope.employee_id:
            abort(404)
    elif scope.role == "manager":
        employee = db.session.get(Employee, leave_request.employee_id)
        if employee is None or employee.department_id not in scope.department_ids:
            abort(404)

    return leave_request


def _commit_or_raise_overlap() -> None:
    """Commit the session, translating an overlap-constraint violation.

    Any other ``IntegrityError`` is re-raised unchanged for the caller
    (route layer) to handle — same pattern as
    ``app.services.scheduling._commit_or_raise_overlap``.
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
                "This employee already has an overlapping pending or "
                "approved leave request."
            ) from error
        raise


def request_leave(
    scope: AccessScope,
    leave_type_id: int,
    starts_at: datetime,
    ends_at: datetime,
    employee_id: int | None = None,
    reason: str | None = None,
) -> LeaveRequest:
    """Create a pending leave request.

    ``employee_id`` defaults to the caller's own employee record.
    Requesting leave on someone else's behalf requires admin/manager (a
    manager only within their own departments) — same on-behalf-of
    pattern as ``app.services.attendance.clock_in``.
    """
    target_employee_id = employee_id if employee_id is not None else scope.employee_id
    if target_employee_id is None:
        raise ValidationError("No employee specified for the leave request.")

    acting_for_self = target_employee_id == scope.employee_id
    if not acting_for_self and scope.role not in _DECIDABLE_ROLES:
        abort(403)

    _validate_employee_for_scope(scope, target_employee_id)
    _validate_leave_type(scope, leave_type_id)

    tz = organization_timezone(scope)
    starts_at = _localize(starts_at, tz)
    ends_at = _localize(ends_at, tz)

    leave_request = LeaveRequest(
        organization_id=scope.organization_id,
        employee_id=target_employee_id,
        leave_type_id=leave_type_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status="pending",
        reason=reason,
        requested_by_user_id=scope.user_id,
    )
    db.session.add(leave_request)
    _commit_or_raise_overlap()
    return leave_request


def list_leave_types(scope: AccessScope) -> list[LeaveType]:
    """Active leave types available to ``scope``'s organization.

    Every role may read this list (it's just a catalog, not a
    privileged view) — needed to populate the "leave type" choice on the
    request form without a route querying the database directly, per the
    project's "routes stay thin" convention.
    """
    return (
        db.session.query(LeaveType)
        .filter(
            LeaveType.organization_id == scope.organization_id,
            LeaveType.is_active.is_(True),
        )
        .order_by(LeaveType.name)
        .all()
    )


def list_leave_requests(
    scope: AccessScope,
    status: str | None = None,
    employee_id: int | None = None,
    covers: tuple[datetime, datetime] | None = None,
) -> list[LeaveRequest]:
    """List leave requests visible to ``scope``.

    Admin: every request in the organization. Manager: only requests for
    employees in departments they manage. Employee: only their own
    requests — same scoping shape as
    ``app.services.scheduling.list_shifts``.

    ``covers``, if given, is a ``(range_start, range_end)`` pair pushed
    into the query as ``starts_at <= range_end AND ends_at >= range_start``
    — Round B fix: ``reports.who_is_on_leave_today`` used to load every
    approved request the organization has ever had and filter "covers
    today" in Python, an unbounded query that only grows with history.
    """
    if scope.role == "employee":
        if scope.employee_id is None:
            return []
        query = db.session.query(LeaveRequest).filter(
            LeaveRequest.organization_id == scope.organization_id,
            LeaveRequest.employee_id == scope.employee_id,
        )
        if status is not None:
            query = query.filter(LeaveRequest.status == status)
        if covers is not None:
            range_start, range_end = covers
            query = query.filter(
                LeaveRequest.starts_at <= range_end,
                LeaveRequest.ends_at >= range_start,
            )
        return query.order_by(LeaveRequest.starts_at).all()

    query = db.session.query(LeaveRequest).filter(
        LeaveRequest.organization_id == scope.organization_id
    )
    if scope.role == "manager":
        query = query.join(
            Employee, Employee.id == LeaveRequest.employee_id
        ).filter(Employee.department_id.in_(scope.department_ids))
    if status is not None:
        query = query.filter(LeaveRequest.status == status)
    if employee_id is not None:
        query = query.filter(LeaveRequest.employee_id == employee_id)
    if covers is not None:
        range_start, range_end = covers
        query = query.filter(
            LeaveRequest.starts_at <= range_end,
            LeaveRequest.ends_at >= range_start,
        )
    return query.order_by(LeaveRequest.starts_at).all()


def conflicting_shifts_for(scope: AccessScope, leave_request: LeaveRequest) -> list:
    """Published shifts overlapping ``leave_request``'s range, if any.

    Only a *published* shift is a real scheduling commitment worth
    surfacing as a conflict; ``availability.shifts_overlapping`` already
    excludes cancelled shifts (never a conflict), so only draft shifts
    need filtering out here. Used both by ``approve_leave`` (to block the
    approval) and by the route layer (to show conflict context on the
    list view before a manager attempts to approve).

    A leave type marked ``blocks_scheduling=False`` never conflicts with
    anything here, matching how ``app.services.scheduling`` treats the
    same flag on the other side of this relationship (see
    ``_check_leave_conflict`` there) — one consistent meaning for the
    flag regardless of which side of the shift/leave relationship is
    being checked.
    """
    leave_type = db.session.get(LeaveType, leave_request.leave_type_id)
    if leave_type is not None and not leave_type.blocks_scheduling:
        return []

    return [
        shift
        for shift in availability.shifts_overlapping(
            scope,
            leave_request.employee_id,
            leave_request.starts_at,
            leave_request.ends_at,
        )
        if shift.status == "published"
    ]


def approve_leave(
    scope: AccessScope, leave_request_id: int, decision_note: str | None = None
) -> LeaveRequest:
    """Approve a pending leave request. Admin/manager only.

    Blocked (with a ``ValidationError`` listing the conflicting shifts)
    if any published, non-cancelled shift overlaps the requested range for
    that employee — the approving manager must resolve the conflict
    (reassign/cancel the shift) themselves; nothing here auto-unassigns
    or auto-cancels a shift. Self-approval is also blocked: an admin or
    manager who happens to also be the requesting employee (compared via
    ``scope.employee_id``, since one user may hold both an admin/manager
    role and a linked employee record) may not approve their own request.
    """
    if scope.role not in _DECIDABLE_ROLES:
        abort(403)

    leave_request = _get_leave_request_for_scope(scope, leave_request_id)

    if scope.employee_id is not None and scope.employee_id == leave_request.employee_id:
        raise ValidationError("You cannot approve your own leave request.")

    if leave_request.status != "pending":
        raise ValidationError("Only a pending leave request can be approved.")

    conflicting_shifts = conflicting_shifts_for(scope, leave_request)
    if conflicting_shifts:
        # Formatted in the organization's own timezone, not left as raw
        # timestamptz values: a bare shift.starts_at's displayed offset
        # depends on the database session, not any timezone the
        # application chose — the same ambient-timezone problem
        # app/__init__.py's local_dt Jinja filter exists to prevent for
        # templates. This is a flashed message built in a service (not a
        # template), so it's formatted the same way local_dt does
        # (astimezone + explicit format) before interpolating.
        tz = organization_timezone(scope)
        shift_descriptions = ", ".join(
            f"#{shift.id} ("
            f"{shift.starts_at.astimezone(tz).strftime('%Y-%m-%d %H:%M')} - "
            f"{shift.ends_at.astimezone(tz).strftime('%Y-%m-%d %H:%M')})"
            for shift in conflicting_shifts
        )
        raise ValidationError(
            "Cannot approve: this employee has published shift(s) that "
            f"overlap this leave request: {shift_descriptions}. Reassign "
            "or cancel the conflicting shift(s) first."
        )

    leave_request.status = "approved"
    leave_request.decided_by_user_id = scope.user_id
    leave_request.decided_at = datetime.now(timezone.utc)
    leave_request.decision_note = decision_note
    # changes excludes decision_note: it's free-text a manager/admin
    # writes and may contain a personal circumstance, which is more
    # sensitive than this audit trail is meant to carry (see
    # app.services.audit's module docstring on keeping changes small
    # and non-sensitive).
    audit_service.record(
        "leave_approved",
        "leave_request",
        entity_id=leave_request.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": leave_request.employee_id},
    )
    # One commit covers both the approval and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return leave_request


def reject_leave(
    scope: AccessScope, leave_request_id: int, decision_note: str
) -> LeaveRequest:
    """Reject a pending leave request. Admin/manager only.

    ``decision_note`` is mandatory — mirrors
    ``app.services.attendance.correct_entry``'s required ``edit_reason``.
    """
    if scope.role not in _DECIDABLE_ROLES:
        abort(403)

    if not decision_note or not decision_note.strip():
        raise ValidationError(
            "A reason is required to reject a leave request.",
            field="decision_note",
        )

    leave_request = _get_leave_request_for_scope(scope, leave_request_id)

    if leave_request.status != "pending":
        raise ValidationError("Only a pending leave request can be rejected.")

    leave_request.status = "rejected"
    leave_request.decided_by_user_id = scope.user_id
    leave_request.decided_at = datetime.now(timezone.utc)
    leave_request.decision_note = decision_note.strip()
    # changes excludes decision_note for the same reason as approve_leave.
    audit_service.record(
        "leave_rejected",
        "leave_request",
        entity_id=leave_request.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": leave_request.employee_id},
    )
    # One commit covers both the rejection and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return leave_request


def cancel_leave(scope: AccessScope, leave_request_id: int) -> LeaveRequest:
    """Cancel a leave request.

    The requesting employee may cancel only their own, and only while it
    is still pending. Admin/manager may cancel any request in their scope
    regardless of status, including an already-approved one (the
    employee's plans changed). ``decided_by_user_id``/``decided_at`` are
    deliberately left untouched here — see the module docstring on
    ``app.models.leave_request.LeaveRequest`` for why that is exactly
    what keeps an approved-then-cancelled request distinguishable from a
    pending-then-cancelled one using the ``status`` column alone.
    """
    leave_request = _get_leave_request_for_scope(scope, leave_request_id)

    is_owner = (
        scope.role == "employee" and scope.employee_id == leave_request.employee_id
    )
    if not is_owner and scope.role not in _DECIDABLE_ROLES:
        abort(403)

    if leave_request.status == "cancelled":
        raise ValidationError("This leave request is already cancelled.")

    if is_owner and leave_request.status != "pending":
        raise ValidationError(
            "You may only cancel your own leave request while it is still "
            "pending; contact an admin or manager for an already-decided "
            "request."
        )

    # previous_status is captured before the overwrite below so an
    # already-approved request's cancellation is distinguishable in the
    # audit trail from a pending request's cancellation (and from the
    # original "leave_approved" entry, via the "leave_cancelled" action
    # name alone) — a real reversal of a decision that was itself
    # audited deserves its own trail, same as any other state
    # transition in this module.
    previous_status = leave_request.status
    leave_request.status = "cancelled"
    audit_service.record(
        "leave_cancelled",
        "leave_request",
        entity_id=leave_request.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={
            "employee_id": leave_request.employee_id,
            "previous_status": previous_status,
        },
    )
    # One commit covers both the cancellation and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return leave_request
