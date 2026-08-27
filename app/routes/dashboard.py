"""Dashboard and reports routes: the "who's working / absent / on leave /
costing what" landing page CLAUDE.md's Product Philosophy section
describes, plus two supporting drill-down reports.

Per this milestone's constraint, every view here only composes data
already computed by ``app.services.reports`` (itself a thin composition
over ``scheduling``/``attendance``/``working_hours``/``leave``/
``labor_cost``) — no route here queries the database directly, and no
route here contains a business calculation of its own.

Confirmed rule A4 is enforced the same way as
``app.routes.labor_cost``: a manager (or admin viewing a manager-style
aggregate) only ever sees department labor-cost *totals*
(``labor_cost.department_cost_summary``) and per-employee *overtime
hours* (never a rate or a cost figure — see
``reports.overtime_summary``'s docstring). Nothing here calls
``labor_cost.range_cost_for_employee`` and renders its ``.rate``/``.cost``
outside the existing, still admin-only ``labor_cost.employee_detail``
route.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import current_user

from app.auth.decorators import login_required, role_required
from app.auth.scope import build_scope_for_user
from app.forms import ClockInForm, ClockOutForm
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services import labor_cost as labor_cost_service
from app.services import leave as leave_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services import working_hours as working_hours_service
from app.services.errors import ValidationError

dashboard_bp = Blueprint("dashboard", __name__)

# Default trailing window for labor-cost totals and the overtime report:
# the last 7 days including today, matching app.routes.labor_cost's own
# default so the two "cost so far" views agree with each other.
_DEFAULT_COST_WINDOW_DAYS = 6

# Default window for the employee's own upcoming-shifts view and the
# hours-trend report: two weeks, wide enough to be useful without
# pulling a whole quarter of data for a simple line/bar report.
_DEFAULT_UPCOMING_DAYS = 13
_DEFAULT_TREND_DAYS = 13


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _default_cost_window(today: date) -> tuple[date, date]:
    return today - timedelta(days=_DEFAULT_COST_WINDOW_DAYS), today


def _time_of_day_greeting(tz) -> str:
    """"Good morning/afternoon/evening", by the organization's own local
    hour (never the server's) — purely cosmetic (Employee Home's
    personal greeting), computed here rather than in the template so
    the template stays free of business/presentation logic per this
    project's own convention.
    """
    hour = datetime.now(tz).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


# Widest date range these per-employee, per-day report loops
# (overtime_summary, hours_trend) will run against a single request — a
# quarter is generous for a routine report but still bounds the
# employees x days query volume against an arbitrary, user-editable
# ?start=/&end= query string.
_MAX_REPORT_RANGE_DAYS = 92


def _clamp_range(start: date, end: date) -> tuple[date, date]:
    if (end - start).days > _MAX_REPORT_RANGE_DAYS:
        start = end - timedelta(days=_MAX_REPORT_RANGE_DAYS)
    return start, end


def _department_cost_totals(scope, departments, start: date, end: date) -> dict:
    """Department id -> ``labor_cost.DepartmentCostSummary`` (or ``None``
    if the date range itself is invalid), for every department visible
    to ``scope``. Never a per-employee figure — rule A4.

    Round A fix: an individual employee missing rate/policy
    configuration for the range no longer blanks the whole department's
    total — ``department_cost_summary`` now isolates that per employee
    and reports it via ``DepartmentCostSummary.unconfigured_employee_count``,
    which the template surfaces as an explicit note alongside the total
    for everyone who *is* configured.
    """
    totals = {}
    for department in departments:
        try:
            totals[department.id] = labor_cost_service.department_cost_summary(
                scope, department.id, start, end
            )
        except ValidationError:
            totals[department.id] = None
    return totals


def _employee_dashboard(scope):
    tz = scheduling_service.organization_timezone(scope)

    if scope.employee_id is None:
        return render_template(
            "dashboard/employee.html",
            greeting=_time_of_day_greeting(tz),
            first_name=None,
            attendance_status=None,
            clock_in_form=None,
            clock_out_form=None,
            todays_shifts=[],
            upcoming_shifts=[],
            recent_hours=[],
            leave_requests=[],
            leave_type_names={},
            tz=tz,
        )

    first_name = employee_service.get_employee(scope, scope.employee_id).first_name
    today = report_service.today_business_date(scope)
    upcoming_shifts = scheduling_service.list_shifts(
        scope, today, today + timedelta(days=_DEFAULT_UPCOMING_DAYS)
    )
    todays_shifts = [shift for shift in upcoming_shifts if shift.business_date == today]

    # Check-in/check-out itself is unchanged, existing functionality
    # (app.routes.attendance) — these forms just give it a second, more
    # prominent entry point here, per this milestone's explicit ask that
    # the primary action be unmistakable rather than buried on a
    # secondary page. Submission posts to the same attendance.clock_in/
    # clock_out routes as ever.
    #
    # A "needs_review" entry (attendance.flag_stale_open_entries) is a
    # real, deliberate exception to both actions: attendance.clock_out
    # rejects it outright (only an admin/manager correction can resolve
    # one — see that function's docstring), and the DB's own open-entry
    # uniqueness constraint blocks a fresh clock-in while it's still
    # unresolved. Offering either button for this state would be a dead
    # end — a click that always fails — so neither form is built here;
    # the template shows a distinct "needs review" state instead.
    attendance_status = report_service.current_attendance_status(scope)
    can_clock_out = bool(attendance_status) and attendance_status["entry"].status == "open"
    clock_in_form = None if attendance_status else ClockInForm()
    clock_out_form = ClockOutForm() if can_clock_out else None

    recent_hours = []
    for offset in range(6, -1, -1):
        business_date = today - timedelta(days=offset)
        recent_hours.append(
            {
                "date": business_date,
                **working_hours_service.scheduled_vs_worked(
                    scope, scope.employee_id, business_date
                ),
            }
        )

    leave_requests = leave_service.list_leave_requests(scope)
    leave_type_names = {lt.id: lt.name for lt in leave_service.list_leave_types(scope)}

    return render_template(
        "dashboard/employee.html",
        greeting=_time_of_day_greeting(tz),
        first_name=first_name,
        attendance_status=attendance_status,
        clock_in_form=clock_in_form,
        clock_out_form=clock_out_form,
        todays_shifts=todays_shifts,
        upcoming_shifts=upcoming_shifts,
        recent_hours=recent_hours,
        leave_requests=leave_requests,
        leave_type_names=leave_type_names,
        tz=tz,
    )


def _manager_or_admin_dashboard(scope):
    department_id = request.args.get("department_id", type=int)
    departments = department_service.list_departments(scope)
    employees = employee_service.list_employees(scope)
    employee_names = {e.id: f"{e.first_name} {e.last_name}" for e in employees}
    # Same "active" definition scheduling.coverage_summary already uses —
    # a terminated/inactive record isn't part of today's headcount.
    total_employees = sum(1 for e in employees if e.employment_status == "active")

    today = report_service.today_business_date(scope)
    working_today = report_service.who_is_working_today(scope, department_id=department_id)
    absent_today = report_service.who_is_absent_today(scope, department_id=department_id)
    on_leave_today = report_service.who_is_on_leave_today(scope, department_id=department_id)
    needs_review_entries = report_service.attendance_needing_review(
        scope, department_id=department_id
    )

    coverage_departments = (
        [d for d in departments if d.id == department_id] if department_id else departments
    )
    coverage = {
        department.id: scheduling_service.coverage_summary(scope, department.id, today)
        for department in coverage_departments
    }

    cost_start, cost_end = _default_cost_window(today)
    cost_totals = _department_cost_totals(
        scope, coverage_departments, cost_start, cost_end
    )
    unconfigured_employee_count = sum(
        summary.unconfigured_employee_count
        for summary in cost_totals.values()
        if summary is not None
    )

    department_names = {department.id: department.name for department in departments}

    return render_template(
        "dashboard/admin.html",
        today=today,
        departments=departments,
        department_id=department_id,
        department_names=department_names,
        employee_names=employee_names,
        total_employees=total_employees,
        working_today=working_today,
        absent_today=absent_today,
        on_leave_today=on_leave_today,
        needs_review_entries=needs_review_entries,
        unconfigured_employee_count=unconfigured_employee_count,
        coverage=coverage,
        cost_start=cost_start,
        cost_end=cost_end,
        cost_totals=cost_totals,
        tz=scheduling_service.organization_timezone(scope),
    )


@dashboard_bp.route("/dashboard", methods=["GET"])
@login_required
def index():
    scope = build_scope_for_user(current_user)
    if scope.role == "employee":
        return _employee_dashboard(scope)
    return _manager_or_admin_dashboard(scope)


# How many trailing days back "My Hours" shows in its daily breakdown —
# deliberately wider than Home's 7-day glance (this is the dedicated
# deep-dive page, per MVP-1_version2.md §16), still bounded rather than
# unbounded.
_MY_HOURS_HISTORY_DAYS = 13


@dashboard_bp.route("/my-hours", methods=["GET"])
@role_required("employee")
def my_hours():
    """Employee-only working-hours page — today / last 7 days / this
    month, all reusing ``working_hours``/``reports`` exactly as Home
    does, never a rate or a cost figure (MVP-1_version2.md §16: "labor
    cost is an administrative/managerial concern," not shown here even
    for the caller's own record).
    """
    scope = build_scope_for_user(current_user)
    tz = scheduling_service.organization_timezone(scope)
    today = report_service.today_business_date(scope)

    daily_history = []
    for offset in range(_MY_HOURS_HISTORY_DAYS, -1, -1):
        business_date = today - timedelta(days=offset)
        daily_history.append(
            {
                "date": business_date,
                **working_hours_service.scheduled_vs_worked(
                    scope, scope.employee_id, business_date
                ),
            }
        )

    week_start = today - timedelta(days=6)
    week_scheduled = sum((day["scheduled_hours"] for day in daily_history[-7:]), Decimal("0"))
    week_worked = sum((day["worked_hours"] for day in daily_history[-7:]), Decimal("0"))

    month_start = today.replace(day=1)
    month_days = [day for day in daily_history if day["date"] >= month_start]
    # If the month is longer than the fetched history window, extend it
    # back day by day rather than silently understating the total.
    if daily_history and daily_history[0]["date"] > month_start:
        extra_date = daily_history[0]["date"] - timedelta(days=1)
        while extra_date >= month_start:
            month_days.insert(
                0,
                {
                    "date": extra_date,
                    **working_hours_service.scheduled_vs_worked(
                        scope, scope.employee_id, extra_date
                    ),
                },
            )
            extra_date -= timedelta(days=1)
    month_scheduled = sum((day["scheduled_hours"] for day in month_days), Decimal("0"))
    month_worked = sum((day["worked_hours"] for day in month_days), Decimal("0"))

    return render_template(
        "dashboard/my_hours.html",
        today=today,
        daily_history=daily_history,
        today_hours=daily_history[-1] if daily_history else None,
        week_start=week_start,
        week_scheduled=week_scheduled,
        week_worked=week_worked,
        week_overtime_hours=report_service.my_overtime_hours(scope, week_start, today),
        month_start=month_start,
        month_scheduled=month_scheduled,
        month_worked=month_worked,
        tz=tz,
    )


@dashboard_bp.route("/reports/overtime", methods=["GET"])
@role_required("admin", "manager")
def overtime_report():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)

    today = report_service.today_business_date(scope)
    default_start, default_end = _default_cost_window(today)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    start, end = _clamp_range(start, end)
    department_id = request.args.get("department_id", type=int)

    summary = []
    if department_id is not None:
        summary = report_service.overtime_summary(scope, department_id, start, end)

    return render_template(
        "reports/overtime.html",
        departments=departments,
        department_id=department_id,
        start=start,
        end=end,
        summary=summary,
    )


@dashboard_bp.route("/reports/hours-trend", methods=["GET"])
@role_required("admin", "manager")
def hours_trend_report():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)

    today = report_service.today_business_date(scope)
    default_start = today - timedelta(days=_DEFAULT_TREND_DAYS)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), today)
    start, end = _clamp_range(start, end)
    department_id = request.args.get("department_id", type=int)

    trend = []
    if department_id is not None:
        trend = report_service.hours_trend(scope, department_id, start, end)

    # Bar width is a presentation-only detail (not a business figure), so
    # it's computed here in the route rather than in the report service.
    max_hours = max((day["total_hours"] for day in trend), default=Decimal("0"))
    for day in trend:
        day["bar_width_percent"] = (
            round(float(day["total_hours"] / max_hours) * 100, 1) if max_hours > 0 else 0
        )

    return render_template(
        "reports/hours_trend.html",
        departments=departments,
        department_id=department_id,
        start=start,
        end=end,
        trend=trend,
    )
