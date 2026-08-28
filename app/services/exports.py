"""CSV export: payroll/accounting-ready data for the five report areas
this milestone requires (Attendance, Working Hours, Overtime, Leave,
Labor Cost).

Every function here takes the caller's ``AccessScope`` and reuses the
exact same data-fetching functions the corresponding HTML report already
calls — never a parallel query path, and never a wider data scope than
the UI grants the same caller. In particular, the labor-cost functions
preserve rule A4 exactly as ``app.services.labor_cost``/
``app.routes.labor_cost`` already enforce it: a manager only ever gets
the same department *total* the HTML view shows them, never a
per-employee rate or cost figure; only ``admin_labor_cost_csv`` (admin
only, mirroring ``routes.labor_cost.employee_detail``'s own
``role_required("admin")`` restriction) returns per-employee line items.

Every ``*_csv`` function returns ``(filename, csv_text)`` — the route
layer is responsible for wrapping that in a ``Response`` with the right
content type/headers (kept out of this module so it stays a pure,
route-independent data transform, consistent with this project's
"business logic outside HTTP handlers" convention).
"""

import csv
import io
from datetime import date, datetime, time
from decimal import Decimal

from flask import abort

from app.auth.scope import AccessScope, get_scoped_or_404
from app.models.department import Department
from app.services import employees as employee_service
from app.services import labor_cost as labor_cost_service
from app.services import leave as leave_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services import working_hours as working_hours_service


def _write_csv(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _employee_names(scope: AccessScope) -> dict[int, str]:
    return {
        employee.id: f"{employee.first_name} {employee.last_name}"
        for employee in employee_service.list_employees(scope)
    }


def attendance_csv(
    scope: AccessScope, start: date, end: date, employee_id: int | None = None
) -> tuple[str, str]:
    """Every attendance entry in ``[start, end]`` visible to ``scope``,
    mirroring exactly what ``app.routes.attendance.list_entries`` shows
    (``reports.attendance_entries_with_context``, same scoping/filtering).
    """
    names = _employee_names(scope)
    context_rows = report_service.attendance_entries_with_context(
        scope, start, end, employee_id=employee_id
    )

    header = [
        "Employee",
        "Date",
        "Clock in",
        "Clock out",
        "Status",
        "Break (minutes)",
        "Worked hours",
        "Late (minutes)",
        "Source",
    ]
    rows = []
    for row in context_rows:
        entry = row["entry"]
        rows.append(
            [
                names.get(entry.employee_id, f"#{entry.employee_id}"),
                entry.business_date.isoformat(),
                entry.started_at.isoformat(),
                entry.ended_at.isoformat() if entry.ended_at else "",
                entry.status,
                entry.break_minutes,
                f"{row['worked_hours']:.2f}" if row["worked_hours"] is not None else "",
                row["late_minutes"] if row["late_minutes"] is not None else "",
                entry.source,
            ]
        )
    return f"attendance_{start.isoformat()}_{end.isoformat()}.csv", _write_csv(header, rows)


def working_hours_csv(scope: AccessScope, department_id: int, start: date, end: date) -> tuple[str, str]:
    """Daily worked hours per employee in ``department_id``, using the
    same batched lookup (``working_hours.worked_seconds_by_range_for_employees``)
    the performance-hardening pass added — one query for the whole
    department/range rather than one per employee.
    """
    department = get_scoped_or_404(Department, department_id, scope)
    employees = [
        employee
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department.id
    ]
    names = {employee.id: f"{employee.first_name} {employee.last_name}" for employee in employees}
    seconds_by_employee = working_hours_service.worked_seconds_by_range_for_employees(
        scope, [employee.id for employee in employees], start, end
    )

    header = ["Employee", "Date", "Worked hours"]
    rows = []
    for employee in employees:
        seconds_by_date = seconds_by_employee.get(employee.id, {})
        for business_date, seconds in sorted(seconds_by_date.items()):
            rows.append(
                [names[employee.id], business_date.isoformat(), f"{Decimal(seconds) / 3600:.2f}"]
            )
    return (
        f"working_hours_{department.code}_{start.isoformat()}_{end.isoformat()}.csv",
        _write_csv(header, rows),
    )


def overtime_csv(scope: AccessScope, department_id: int, start: date, end: date) -> tuple[str, str]:
    """Same summary ``app.routes.dashboard.overtime_report`` renders
    (``reports.overtime_summary``) — one row per employee. Only overtime
    hours, never a rate or cost (rule A4 — see that function's docstring
    on why only ``.hours``/``.category`` are ever read from its
    underlying line items).
    """
    summary = report_service.overtime_summary(scope, department_id, start, end)

    header = ["Employee", "Overtime hours", "Configured"]
    rows = [
        [
            f"{row['employee'].first_name} {row['employee'].last_name}",
            f"{row['ot_hours']:.2f}" if row["configured"] else "",
            "yes" if row["configured"] else "no",
        ]
        for row in summary
    ]
    return f"overtime_{start.isoformat()}_{end.isoformat()}.csv", _write_csv(header, rows)


def _leave_covers_range(scope: AccessScope, start: date | None, end: date | None):
    """Build ``leave_service.list_leave_requests``'s ``covers`` tuple, or
    ``None`` if no range was given — matching
    ``app.routes.leave.list_requests``'s own default of no date filter
    at all (status/employee only), so an export with no range selected
    returns exactly the same set the HTML list view would.

    Built in the organization's own timezone, not UTC — same rule
    ``app.services.audit.list_entries`` follows for an identical
    date-to-timestamptz-range conversion (see that function's
    docstring): a bare UTC range can silently shift which leave requests
    count as "covering" a given calendar date for any organization not
    on UTC.
    """
    if start is None or end is None:
        return None
    tz = scheduling_service.organization_timezone(scope)
    return (
        datetime.combine(start, time.min, tzinfo=tz),
        datetime.combine(end, time.max, tzinfo=tz),
    )


def leave_csv(
    scope: AccessScope,
    status: str | None = None,
    employee_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> tuple[str, str]:
    """Leave requests visible to ``scope``, same scoping/filters as
    ``app.routes.leave.list_requests`` (``leave_service.list_leave_requests``).
    ``start``/``end`` are an optional extra narrowing this export offers
    beyond what the HTML list view filters by (never wider than what the
    view could already show — see ``_leave_covers_range``).
    """
    names = _employee_names(scope)
    leave_type_names = {lt.id: lt.name for lt in leave_service.list_leave_types(scope)}
    covers = _leave_covers_range(scope, start, end)
    requests = leave_service.list_leave_requests(
        scope, status=status, employee_id=employee_id, covers=covers
    )

    header = ["Employee", "Leave type", "Start", "End", "Status", "Reason"]
    rows = [
        [
            names.get(request.employee_id, f"#{request.employee_id}"),
            leave_type_names.get(request.leave_type_id, f"#{request.leave_type_id}"),
            request.starts_at.isoformat(),
            request.ends_at.isoformat(),
            request.status,
            request.reason or "",
        ]
        for request in requests
    ]
    suffix = f"{start.isoformat()}_{end.isoformat()}" if covers else "all"
    return f"leave_{suffix}.csv", _write_csv(header, rows)


def labor_cost_csv(scope: AccessScope, department_id: int, start: date, end: date) -> tuple[str, str]:
    """Department labor-cost *total* only — the manager-safe aggregate
    ``app.routes.labor_cost.department_totals`` renders
    (``labor_cost.department_cost_summary``). Never a per-employee
    figure; see ``admin_labor_cost_csv`` for the admin-only payroll
    export that does carry one.
    """
    department = get_scoped_or_404(Department, department_id, scope)
    summary = labor_cost_service.department_cost_summary(scope, department.id, start, end)

    header = ["Department", "Start", "End", "Total cost", "Unconfigured employees"]
    rows = [
        [
            department.name,
            start.isoformat(),
            end.isoformat(),
            f"{summary.total:.2f}",
            summary.unconfigured_employee_count,
        ]
    ]
    return (
        f"labor_cost_{department.code}_{start.isoformat()}_{end.isoformat()}.csv",
        _write_csv(header, rows),
    )


def admin_labor_cost_csv(scope: AccessScope, employee_id: int, start: date, end: date) -> tuple[str, str]:
    """Payroll-ready cost breakdown for one employee — admin only,
    mirroring exactly the scope of ``app.routes.labor_cost.employee_detail``
    (``role_required("admin")``, ``employee_service.get_employee`` for
    the org-scoped 404, ``labor_cost.range_cost_for_employee`` for the
    data): this is the one export in this module that carries a rate/cost
    per employee, so it must never be reachable by a manager, and must
    never widen scope beyond the single employee that route already
    shows. Enforced here too (defense in depth, same belt-and-suspenders
    pattern used throughout this codebase), not only by the route
    decorator.
    """
    if scope.role != "admin":
        abort(403)

    employee = employee_service.get_employee(scope, employee_id)
    employee_name = f"{employee.first_name} {employee.last_name}"
    line_items = labor_cost_service.range_cost_for_employee(scope, employee.id, start, end)

    header = ["Employee", "Date", "Category", "Hours", "Rate", "Multiplier", "Cost"]
    rows = [
        [
            employee_name,
            item.business_date.isoformat(),
            item.category,
            f"{item.hours:.2f}",
            f"{item.rate:.2f}",
            f"{item.multiplier:.2f}",
            f"{item.cost:.2f}",
        ]
        for item in line_items
    ]
    return (
        f"labor_cost_payroll_{employee.employee_number}_{start.isoformat()}_{end.isoformat()}.csv",
        _write_csv(header, rows),
    )
