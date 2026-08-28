"""Working hours service: derives worked/scheduled hours from attendance.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, independent of whatever the route layer already
checked — same pattern as ``app.services.attendance``/``scheduling``.

This module deliberately contains no multiplier/money logic — see
``app.services.overtime`` for the (pure, DB-free) tiering calculations
that consume the totals computed here.
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import abort

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.attendance_entry import AttendanceEntry
from app.models.employee import Employee
from app.models.shift import Shift
from app.services.errors import ValidationError

_SECONDS_PER_HOUR = Decimal(3600)


def _ensure_employee_visible(scope: AccessScope, employee_id: int) -> Employee:
    """Confirm ``employee_id`` may have their hours viewed by the caller.

    Mirrors ``app.services.attendance._validate_employee_for_scope``'s
    organization/department checks, but a 404 (not a ``ValidationError``)
    for an out-of-scope employee — same IDOR defense as
    ``app.services.attendance._get_entry_for_scope``: a caller cannot
    distinguish "doesn't exist" from "exists but you can't see it".
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
        abort(404)
    if scope.role == "employee" and employee_id != scope.employee_id:
        abort(404)
    if scope.role == "manager" and employee.department_id not in scope.department_ids:
        abort(404)
    return employee


def _worked_seconds(entry: AttendanceEntry) -> int:
    """Paid worked time for one closed attendance entry, break excluded."""
    duration_seconds = int((entry.ended_at - entry.started_at).total_seconds())
    return duration_seconds - entry.break_minutes * 60


def _scheduled_seconds(shift: Shift) -> int:
    duration_seconds = int((shift.ends_at - shift.starts_at).total_seconds())
    return duration_seconds - shift.break_minutes * 60


def _hours(seconds: int) -> Decimal:
    return Decimal(seconds) / _SECONDS_PER_HOUR


def worked_seconds_for_day(
    scope: AccessScope, employee_id: int, business_date: date
) -> int:
    """Total paid worked seconds for one employee on one business date.

    Only ``closed`` attendance entries count — an ``open`` or
    ``needs_review`` entry has unresolved time that is not paid time
    until resolved, per the attendance module's existing philosophy. An
    overnight entry is not re-split here: ``business_date`` is already
    the attribution date computed once, at creation time, by
    ``app.services.scheduling.business_date_for``.
    """
    _ensure_employee_visible(scope, employee_id)

    entries = (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.organization_id == scope.organization_id,
            AttendanceEntry.employee_id == employee_id,
            AttendanceEntry.business_date == business_date,
            AttendanceEntry.status == "closed",
        )
        .all()
    )
    return sum(_worked_seconds(entry) for entry in entries)


def worked_seconds_by_range(
    scope: AccessScope, employee_id: int, start_date: date, end_date: date
) -> dict[date, int]:
    """Total paid worked seconds for one employee, per business date, for
    every date in ``[start_date, end_date]`` that has at least one closed
    entry (a date with none is simply absent from the returned dict —
    callers should treat a missing key as zero, same as ``worked_seconds_
    for_day`` would return for that date).

    One query for the whole range plus one visibility check, instead of
    ``worked_seconds_for_day`` called once per day (two queries each) —
    the actual fix for the N+1 pattern
    ``labor_cost.range_cost_for_employee`` used to have (a measured ~2.2s
    admin dashboard load with just 12 employees / 4 departments). Kept
    entirely separate from ``worked_seconds_for_day`` rather than
    reimplementing it in terms of this: that function's single-day
    contract and query shape stay exactly as they were for its own
    existing callers (``scheduled_vs_worked``, and any single-day use
    elsewhere), so this is purely an additive fast path for a caller that
    genuinely needs a whole range.
    """
    _ensure_employee_visible(scope, employee_id)

    entries = (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.organization_id == scope.organization_id,
            AttendanceEntry.employee_id == employee_id,
            AttendanceEntry.business_date >= start_date,
            AttendanceEntry.business_date <= end_date,
            AttendanceEntry.status == "closed",
        )
        .all()
    )
    seconds_by_date: dict[date, int] = {}
    for entry in entries:
        seconds_by_date[entry.business_date] = (
            seconds_by_date.get(entry.business_date, 0) + _worked_seconds(entry)
        )
    return seconds_by_date


def _ensure_employees_visible(scope: AccessScope, employee_ids: list[int]) -> None:
    """Batched form of ``_ensure_employee_visible``: confirms every id in
    ``employee_ids`` is visible to ``scope`` (same organization, and for
    a manager, one of their managed departments) in one query, instead of
    one query per employee_id.

    Same 404-not-403 IDOR posture as ``_ensure_employee_visible``: a
    caller cannot distinguish "doesn't exist" from "exists but you can't
    see it", so any id that fails to resolve aborts the whole batch
    rather than silently dropping it from the result.
    """
    if not employee_ids:
        return

    requested_ids = set(employee_ids)

    if scope.role == "employee":
        if requested_ids - {scope.employee_id}:
            abort(404)
        return

    query = db.session.query(Employee.id).filter(
        Employee.id.in_(requested_ids),
        Employee.organization_id == scope.organization_id,
    )
    if scope.role == "manager":
        query = query.filter(Employee.department_id.in_(scope.department_ids))

    visible_ids = {row[0] for row in query.all()}
    if visible_ids != requested_ids:
        abort(404)


def worked_seconds_by_range_for_employees(
    scope: AccessScope, employee_ids: list[int], start_date: date, end_date: date
) -> dict[int, dict[date, int]]:
    """``worked_seconds_by_range`` for every employee in ``employee_ids``
    at once: one query for every employee's closed entries across the
    whole range (plus one batched visibility check), instead of
    ``worked_seconds_by_range`` called once per employee.

    This is the actual fix for the N+1 pattern
    ``reports.overtime_summary``/``reports.hours_trend`` used to have at
    department-employee-count scale (see ``labor_cost.range_cost_for_employees``
    and each report function's own docstring) — the same class of fix
    ``worked_seconds_by_range`` itself already made for a single
    employee's day-by-day loop.

    An employee id with no closed entries in the range is simply absent
    from its own sub-dict (same "missing key means zero" contract as
    ``worked_seconds_by_range``), and an ``employee_ids`` id that never
    had any entries at all is still present in the top-level dict, mapped
    to an empty ``{}`` — every requested id gets an entry, so a caller
    can always safely do ``result[employee_id]`` for a visible employee.
    """
    if not employee_ids:
        return {}

    _ensure_employees_visible(scope, employee_ids)

    entries = (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.organization_id == scope.organization_id,
            AttendanceEntry.employee_id.in_(employee_ids),
            AttendanceEntry.business_date >= start_date,
            AttendanceEntry.business_date <= end_date,
            AttendanceEntry.status == "closed",
        )
        .all()
    )

    seconds_by_employee: dict[int, dict[date, int]] = {
        employee_id: {} for employee_id in employee_ids
    }
    for entry in entries:
        per_employee = seconds_by_employee[entry.employee_id]
        per_employee[entry.business_date] = (
            per_employee.get(entry.business_date, 0) + _worked_seconds(entry)
        )
    return seconds_by_employee


def worked_seconds_for_week(
    scope: AccessScope,
    employee_id: int,
    week_start_date: date,
    week_start_day: int,
) -> int:
    """Total paid worked seconds for one employee across a 7-day window
    starting at ``week_start_date``.

    ``week_start_day`` (0=Monday..6=Sunday, matching
    ``date.weekday()``) must be the weekday of ``week_start_date`` — a
    cheap, defensive check that the caller actually passed the start of
    a week under the organization's configured convention, not an
    arbitrary date.
    """
    if week_start_date.weekday() != week_start_day:
        raise ValidationError(
            "week_start_date does not fall on week_start_day."
        )

    _ensure_employee_visible(scope, employee_id)

    week_end_date = week_start_date + timedelta(days=6)
    entries = (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.organization_id == scope.organization_id,
            AttendanceEntry.employee_id == employee_id,
            AttendanceEntry.business_date >= week_start_date,
            AttendanceEntry.business_date <= week_end_date,
            AttendanceEntry.status == "closed",
        )
        .all()
    )
    return sum(_worked_seconds(entry) for entry in entries)


def scheduled_vs_worked(
    scope: AccessScope, employee_id: int, business_date: date
) -> dict:
    """Scheduled hours (published shifts) vs. worked hours (closed
    attendance) vs. the difference, for one employee on one business
    date — answers CLAUDE.md's "Scheduled Hours / Worked Hours /
    Difference" requirement directly.
    """
    _ensure_employee_visible(scope, employee_id)

    shifts = (
        db.session.query(Shift)
        .filter(
            Shift.organization_id == scope.organization_id,
            Shift.employee_id == employee_id,
            Shift.business_date == business_date,
            Shift.status == "published",
        )
        .all()
    )
    scheduled_seconds = sum(_scheduled_seconds(shift) for shift in shifts)
    worked_seconds = worked_seconds_for_day(scope, employee_id, business_date)

    scheduled_hours = _hours(scheduled_seconds)
    worked_hours = _hours(worked_seconds)
    return {
        "scheduled_hours": scheduled_hours,
        "worked_hours": worked_hours,
        "difference_hours": worked_hours - scheduled_hours,
    }
