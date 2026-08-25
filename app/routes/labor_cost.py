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
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services import labor_cost as labor_cost_service
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
    department_id = request.args.get("department_id", type=int)

    departments = department_service.list_departments(scope)
    total = None
    unconfigured_employee_count = 0

    if department_id is not None:
        try:
            summary = labor_cost_service.department_cost_summary(
                scope, department_id, start, end
            )
            total = summary.total
            unconfigured_employee_count = summary.unconfigured_employee_count
        except ValidationError as error:
            flash(error.message, "error")

    return render_template(
        "labor_cost/index.html",
        departments=departments,
        department_id=department_id,
        start=start,
        end=end,
        total=total,
        unconfigured_employee_count=unconfigured_employee_count,
        is_admin=scope.role == "admin",
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
