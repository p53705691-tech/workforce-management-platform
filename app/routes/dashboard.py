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

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import current_user

from app.auth.decorators import login_required, role_required
from app.auth.scope import build_scope_for_user
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
    if scope.employee_id is None:
        return render_template(
            "dashboard/employee.html",
            upcoming_shifts=[],
            recent_hours=[],
            leave_requests=[],
            leave_type_names={},
            tz=scheduling_service.organization_timezone(scope),
        )

    today = report_service.today_business_date(scope)
    upcoming_shifts = scheduling_service.list_shifts(
        scope, today, today + timedelta(days=_DEFAULT_UPCOMING_DAYS)
    )

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
        upcoming_shifts=upcoming_shifts,
        recent_hours=recent_hours,
        leave_requests=leave_requests,
        leave_type_names=leave_type_names,
        tz=scheduling_service.organization_timezone(scope),
    )


def _manager_or_admin_dashboard(scope):
    department_id = request.args.get("department_id", type=int)
    departments = department_service.list_departments(scope)
    employees = employee_service.list_employees(scope)
    employee_names = {e.id: f"{e.first_name} {e.last_name}" for e in employees}

    today = report_service.today_business_date(scope)
    working_today = report_service.who_is_working_today(scope, department_id=department_id)
    absent_today = report_service.who_is_absent_today(scope, department_id=department_id)
    on_leave_today = report_service.who_is_on_leave_today(scope, department_id=department_id)

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

    department_names = {department.id: department.name for department in departments}

    return render_template(
        "dashboard/admin.html",
        today=today,
        departments=departments,
        department_id=department_id,
        department_names=department_names,
        employee_names=employee_names,
        working_today=working_today,
        absent_today=absent_today,
        on_leave_today=on_leave_today,
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


@dashboard_bp.route("/reports/overtime", methods=["GET"])
@role_required("admin", "manager")
def overtime_report():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)

    today = report_service.today_business_date(scope)
    default_start, default_end = _default_cost_window(today)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
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
