"""Labor cost routes: department/date-range totals, and an admin-only
per-employee cost breakdown.

Confirmed rule A4 draws a hard line between two views, enforced here at
the route level (not just in a template):

- Department **totals** (``GET /labor-cost``): admin or manager. A
  manager only ever sees a single number for a department they manage —
  never a per-employee figure, never an hourly rate.
- Per-employee **detail** (``GET /labor-cost/employees/<id>``): admin
  only. This view's line items imply an hourly rate (``LineItem.rate``
  is rendered directly), which is exactly what A4 keeps away from
  managers, so this route is never reachable by ``role_required``
  outside ``"admin"``.

Every view builds an ``AccessScope`` and delegates all authorization and
data access to ``app.services.labor_cost`` — no route here queries the
database directly.
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, flash, render_template, request
from flask_login import current_user

from app.auth.decorators import role_required
from app.auth.scope import build_scope_for_user
from app.routes import csv_response, pdf_response
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services import exports as export_service
from app.services import labor_cost as labor_cost_service
from app.services import pdf_reports as pdf_report_service
from app.services import reports as report_service
from app.services.errors import ValidationError

labor_cost_bp = Blueprint("labor_cost", __name__, url_prefix="/labor-cost")

# Default visible window when no ?start=/&end= query params are given:
# the trailing 7 days including today, matching a "cost so far this
# week" report.
_DEFAULT_WINDOW_DAYS = 6


def _default_date_range(scope) -> tuple[date, date]:
    # Round B fix: org-local "today" (rule A1), not the server's — see
    # app.routes.schedule's identical fix for the full rationale.
    today = report_service.today_business_date(scope)
    return today - timedelta(days=_DEFAULT_WINDOW_DAYS), today


# Same bound as app.routes.dashboard's identical constant: these views
# also run a per-employee, per-day cost computation, so an arbitrary
# user-editable ?start=/&end= must not be allowed to multiply that
# unboundedly.
_MAX_REPORT_RANGE_DAYS = 92


def _clamp_range(start: date, end: date) -> tuple[date, date]:
    if (end - start).days > _MAX_REPORT_RANGE_DAYS:
        start = end - timedelta(days=_MAX_REPORT_RANGE_DAYS)
    return start, end


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


@labor_cost_bp.route("", methods=["GET"])
@role_required("admin", "manager")
def department_totals():
    scope = build_scope_for_user(current_user)
    default_start, default_end = _default_date_range(scope)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    start, end = _clamp_range(start, end)
    department_id = request.args.get("department_id", type=int)

    export_format = request.args.get("format")
    if export_format and department_id is not None:
        if export_format == "csv":
            filename, csv_text = export_service.labor_cost_csv(scope, department_id, start, end)
            return csv_response(filename, csv_text)
        if export_format == "pdf":
            pdf_bytes = pdf_report_service.labor_cost_pdf(scope, department_id, start, end)
            return pdf_response(f"labor_cost_{start.isoformat()}_{end.isoformat()}.pdf", pdf_bytes)

    departments = department_service.list_departments(scope)
    total = None
    unconfigured_employee_count = 0
    is_admin = scope.role == "admin"
    department_employees = []

    if department_id is not None:
        try:
            summary = labor_cost_service.department_cost_summary(
                scope, department_id, start, end
            )
            total = summary.total
            unconfigured_employee_count = summary.unconfigured_employee_count
        except ValidationError as error:
            flash(error.message, "error")

        # Per-employee drill-down links only — never a figure here. Admin
        # only: rule A4 keeps even the *existence* of a per-employee cost
        # view away from a manager, not just its numbers. Not filtered to
        # active employees: department_cost_summary's total above prices
        # every employment status, so a terminated employee who still
        # contributed cost in this range must have a matching drill-down
        # row, or the total and the breakdown silently disagree.
        if is_admin:
            department_employees = [
                employee
                for employee in employee_service.list_employees(scope)
                if employee.department_id == department_id
            ]

    return render_template(
        "labor_cost/index.html",
        departments=departments,
        department_id=department_id,
        start=start,
        end=end,
        total=total,
        unconfigured_employee_count=unconfigured_employee_count,
        is_admin=is_admin,
        department_employees=department_employees,
    )


@labor_cost_bp.route("/employees/<int:employee_id>", methods=["GET"])
@role_required("admin")
def employee_detail(employee_id):
    scope = build_scope_for_user(current_user)
    # Org-scoped 404 even though role_required already restricts this
    # route to admins — same defense-in-depth pattern used everywhere
    # else in this project.
    employee = employee_service.get_employee(scope, employee_id)

    default_start, default_end = _default_date_range(scope)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    start, end = _clamp_range(start, end)

    export_format = request.args.get("format")
    if export_format == "csv":
        filename, csv_text = export_service.admin_labor_cost_csv(scope, employee_id, start, end)
        return csv_response(filename, csv_text)
    if export_format == "pdf":
        pdf_bytes = pdf_report_service.admin_labor_cost_pdf(scope, employee_id, start, end)
        return pdf_response(f"labor_cost_payroll_{start.isoformat()}_{end.isoformat()}.pdf", pdf_bytes)

    line_items = []
    try:
        line_items = labor_cost_service.range_cost_for_employee(
            scope, employee_id, start, end
        )
    except ValidationError as error:
        flash(error.message, "error")

    total = sum((item.cost for item in line_items), Decimal("0.00"))

    return render_template(
        "labor_cost/employee_detail.html",
        employee=employee,
        start=start,
        end=end,
        line_items=line_items,
        total=total,
    )
