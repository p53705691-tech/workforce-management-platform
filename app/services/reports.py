"""Reports service: read-only composition over already-verified services.

Per this milestone's confirmed constraint (see the M8 plan and
CLAUDE.md's Source of Truth section): every number here comes from an
existing, already-tested service function
(``scheduling``/``attendance``/``working_hours``/``leave``/``labor_cost``/
``overtime``). Nothing in this module invents a new hours formula, a new
cost formula, or a new overtime rule — it only aggregates or filters data
those modules already compute correctly.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, same pattern as every other service module in this
project.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from flask import abort

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.department import Department
from app.services import attendance as attendance_service
from app.services import employees as employee_service
from app.services import labor_cost as labor_cost_service
from app.services import leave as leave_service
from app.services import scheduling as scheduling_service
from app.services import working_hours as working_hours_service
from app.services.errors import ValidationError

_SECONDS_PER_HOUR = Decimal(3600)


def today_business_date(scope: AccessScope) -> date:
    """"Today", attributed per rule A1 (the organization's local date),
    reused by every "as of today" report below instead of each one
    recomputing it — see ``scheduling.business_date_for``.
    """
    tz = scheduling_service.organization_timezone(scope)
    return scheduling_service.business_date_for(datetime.now(timezone.utc), tz)


def who_is_working_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Published shifts whose ``business_date`` is today, scoped to
    ``scope`` (and further to ``department_id`` if given).

    A thin filter over ``scheduling.list_shifts`` — that function already
    returns every status for admin/manager, so only the "published"
    filter is added here; no new query logic.
    """
    today = today_business_date(scope)
    shifts = scheduling_service.list_shifts(scope, today, today, department_id=department_id)
    return [shift for shift in shifts if shift.status == "published"]


def who_is_on_leave_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Approved leave requests whose range covers today, scoped to
    ``scope`` (and further to ``department_id`` if given).

    Composed from ``leave.list_leave_requests`` — the "does this range
    cover today" comparison is pushed into the query itself via the
    ``covers`` parameter (Round B fix: this used to load every approved
    request the organization has ever had and filter in Python, an
    unbounded query that only grows with history) rather than an invented
    business rule of its own.
    """
    today = today_business_date(scope)
    tz = scheduling_service.organization_timezone(scope)
    day_start = datetime.combine(today, time.min, tzinfo=tz)
    day_end = datetime.combine(today, time.max, tzinfo=tz)

    covering_today = leave_service.list_leave_requests(
        scope, status="approved", covers=(day_start, day_end)
    )

    if department_id is None:
        return covering_today

    department_employee_ids = {
        employee.id
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department_id
    }
    return [
        leave_request
        for leave_request in covering_today
        if leave_request.employee_id in department_employee_ids
    ]


def who_is_absent_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Employees scheduled (a published shift today) with no attendance
    entry at all for today, and not on approved leave covering today (an
    employee on leave is a different classification, not "absent").

    Composed entirely from ``who_is_working_today`` (this module),
    ``attendance.list_entries`` and ``who_is_on_leave_today``.

    Round B fix: this used to require the attendance entry's ``shift_id``
    to match the specific shift being checked. But
    ``attendance._match_shift`` deliberately leaves ``shift_id`` NULL
    whenever zero or *more than one* published shift falls within the
    clock-in grace window — that's "I could not decide which shift this
    belongs to", not "this employee did not work". An employee who clocks
    in early enough to miss the grace window, or who has two shifts the
    same day, was incorrectly reported absent despite being clocked in.
    Presence is now "does this employee have any attendance entry today
    at all", independent of which (if any) shift it links to.
    """
    shifts_today = who_is_working_today(scope, department_id=department_id)
    if not shifts_today:
        return []

    today = today_business_date(scope)
    entries_today = attendance_service.list_entries(scope, today, today)
    present_employee_ids = {entry.employee_id for entry in entries_today}
    on_leave_employee_ids = {
        leave_request.employee_id
        for leave_request in who_is_on_leave_today(scope, department_id=department_id)
    }
    employees_by_id = {
        employee.id: employee for employee in employee_service.list_employees(scope)
    }

    absent = []
    seen_employee_ids = set()
    for shift in shifts_today:
        if shift.employee_id in present_employee_ids:
            continue
        if shift.employee_id in on_leave_employee_ids:
            continue
        if shift.employee_id in seen_employee_ids:
            continue
        employee = employees_by_id.get(shift.employee_id)
        if employee is None:
            continue
        seen_employee_ids.add(shift.employee_id)
        absent.append(employee)
    return absent


def _department_employees(scope: AccessScope, department_id: int) -> list:
    """Employees of ``department_id``, after confirming the caller may
    report on it (same manager/department and existence checks as
    ``labor_cost.department_cost_summary``).
    """
    if scope.role == "manager" and department_id not in scope.department_ids:
        abort(404)

    department = (
        db.session.query(Department)
        .filter(
            Department.id == department_id,
            Department.organization_id == scope.organization_id,
        )
        .first()
    )
    if department is None:
        abort(404)

    return [
        employee
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department_id
    ]


def _date_range(start_date: date, end_date: date) -> list[date]:
    span = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(span + 1)]


def overtime_summary(
    scope: AccessScope, department_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Per-employee total overtime hours (daily + weekly OT combined) for
    a department over a date range.

    Reuses ``labor_cost.range_cost_for_employee``'s already-correct daily
    and weekly overtime tiering and reclassification (so a hand-rolled
    version here could never accidentally double-count an hour under two
    multipliers) rather than re-deriving it. Only ``LineItem.hours`` and
    ``.category`` are ever read — never ``.rate`` or ``.cost`` — so this
    can never surface a pay rate or a per-employee cost figure (rule A4),
    even though the underlying line items technically carry one.

    Ambiguity resolved here: reusing ``range_cost_for_employee`` means an
    employee with no pay rate or overtime policy configured for the range
    raises the same ``ValidationError`` labor cost reporting already
    raises for that gap. Since this is an hours report, not a money one,
    failing the entire report for every other employee over one missing
    rate would be worse than the alternative: that employee is returned
    with ``"configured": False`` and no hours figure, and the route
    surfaces this as a per-row note instead of failing the page.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

    employees = _department_employees(scope, department_id)

    summary = []
    for employee in employees:
        try:
            line_items = labor_cost_service.range_cost_for_employee(
                scope, employee.id, start_date, end_date
            )
        except ValidationError:
            summary.append({"employee": employee, "ot_hours": None, "configured": False})
            continue

        ot_hours = sum(
            (item.hours for item in line_items if item.category != "regular"),
            Decimal("0"),
        )
        summary.append({"employee": employee, "ot_hours": ot_hours, "configured": True})
    return summary


def hours_trend(
    scope: AccessScope, department_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Per-day total worked hours for a department across a date range —
    a minimal aggregation answering "how are working hours changing over
    time", composed entirely from
    ``working_hours.worked_seconds_for_day`` per employee per day. No new
    hours formula.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

    employees = _department_employees(scope, department_id)

    trend = []
    for business_date in _date_range(start_date, end_date):
        total_seconds = sum(
            working_hours_service.worked_seconds_for_day(scope, employee.id, business_date)
            for employee in employees
        )
        trend.append(
            {
                "date": business_date,
                "total_hours": Decimal(total_seconds) / _SECONDS_PER_HOUR,
            }
        )
    return trend
