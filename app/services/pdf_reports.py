"""PDF export: professional, printable reports for the same five report
areas ``app.services.exports`` covers as CSV.

Every function here takes the caller's ``AccessScope`` and calls exactly
the same service functions ``exports.py``/the HTML reports already use —
see that module's docstring for the authorization/data-scope guarantees
this inherits (in particular: never a per-employee rate/cost outside
``admin_labor_cost_pdf``, matching ``routes.labor_cost.employee_detail``'s
``role_required("admin")`` restriction exactly).

``_render`` is the one shared "report chrome" builder (org name, report
title, date range, generated-at timestamp, page numbers) so every PDF in
this codebase looks like the same product, not five different ones — the
colors below are the same values ``static/css/tokens.css`` defines for
``--ink``/``--accent``/``--line`` (light theme, the only sensible choice
for print), converted from HSL to RGB once here rather than duplicating
a second color system.
"""

import io
from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal

from flask import abort
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle

from app.auth.scope import AccessScope, get_scoped_or_404
from app.models.department import Department
from app.models.organization import Organization
from app.extensions import db
from app.services import employees as employee_service
from app.services import labor_cost as labor_cost_service
from app.services import leave as leave_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services import working_hours as working_hours_service

INK = colors.HexColor("#181F2F")
ACCENT = colors.HexColor("#3155D8")
LINE = colors.HexColor("#D3D7DE")
MUTED = colors.HexColor("#5A6472")

_TITLE_STYLE = ParagraphStyle("Title", fontSize=16, textColor=INK, spaceAfter=2, leading=20)
_SUBTITLE_STYLE = ParagraphStyle("Subtitle", fontSize=10, textColor=MUTED, spaceAfter=14)


def _organization_name(organization_id: int) -> str:
    organization = db.session.get(Organization, organization_id)
    return organization.name if organization is not None else ""


def _render(title: str, organization_id: int, subtitle: str, header: list[str], rows: list[list]) -> bytes:
    """Build one table-based PDF report. Returns raw PDF bytes.

    Never receives raw model objects — every caller below has already
    turned its data into plain strings, exactly as it would for a CSV
    row, so this function has no way to accidentally render a field
    (e.g. a rate) its caller didn't explicitly decide to include.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title=title,
    )

    org_name = _organization_name(organization_id)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    elements = [
        Paragraph(org_name, ParagraphStyle("Org", fontSize=9, textColor=MUTED, spaceAfter=4)),
        Paragraph(title, _TITLE_STYLE),
        Paragraph(f"{subtitle} &middot; Generated {generated_at}", _SUBTITLE_STYLE),
    ]

    table_data = [header] + [[str(cell) for cell in row] for row in rows]
    if not rows:
        elements.append(Paragraph("No data for this range.", _SUBTITLE_STYLE))
    else:
        table = Table(table_data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), INK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, 0), 8),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                    ("TOPPADDING", (0, 1), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F5F7")]),
                ]
            )
        )
        elements.append(table)

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, org_name)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _employee_names(scope: AccessScope) -> dict[int, str]:
    return {
        employee.id: f"{employee.first_name} {employee.last_name}"
        for employee in employee_service.list_employees(scope)
    }


def attendance_pdf(
    scope: AccessScope, start: date, end: date, employee_id: int | None = None
) -> bytes:
    names = _employee_names(scope)
    context_rows = report_service.attendance_entries_with_context(
        scope, start, end, employee_id=employee_id
    )
    header = ["Employee", "Date", "Clock in", "Clock out", "Worked", "Status"]
    rows = [
        [
            names.get(row["entry"].employee_id, f"#{row['entry'].employee_id}"),
            row["entry"].business_date.isoformat(),
            row["entry"].started_at.strftime("%H:%M"),
            row["entry"].ended_at.strftime("%H:%M") if row["entry"].ended_at else "—",
            f"{row['worked_hours']:.2f}h" if row["worked_hours"] is not None else "—",
            row["entry"].status,
        ]
        for row in context_rows
    ]
    return _render(
        "Attendance Report",
        scope.organization_id,
        f"{start.isoformat()} to {end.isoformat()}",
        header,
        rows,
    )


def working_hours_pdf(scope: AccessScope, department_id: int, start: date, end: date) -> bytes:
    department = get_scoped_or_404(Department, department_id, scope)
    employees = [
        employee
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department.id
    ]
    seconds_by_employee = working_hours_service.worked_seconds_by_range_for_employees(
        scope, [employee.id for employee in employees], start, end
    )
    header = ["Employee", "Date", "Worked hours"]
    rows = []
    for employee in employees:
        for business_date, seconds in sorted(seconds_by_employee.get(employee.id, {}).items()):
            rows.append(
                [
                    f"{employee.first_name} {employee.last_name}",
                    business_date.isoformat(),
                    f"{Decimal(seconds) / 3600:.2f}",
                ]
            )
    return _render(
        "Working Hours Report",
        scope.organization_id,
        f"{department.name} · {start.isoformat()} to {end.isoformat()}",
        header,
        rows,
    )


def overtime_pdf(scope: AccessScope, department_id: int, start: date, end: date) -> bytes:
    summary = report_service.overtime_summary(scope, department_id, start, end)
    header = ["Employee", "Overtime hours", "Configured"]
    rows = [
        [
            f"{row['employee'].first_name} {row['employee'].last_name}",
            f"{row['ot_hours']:.2f}" if row["configured"] else "—",
            "Yes" if row["configured"] else "No",
        ]
        for row in summary
    ]
    return _render(
        "Overtime Report",
        scope.organization_id,
        f"{start.isoformat()} to {end.isoformat()}",
        header,
        rows,
    )


def leave_pdf(
    scope: AccessScope,
    status: str | None = None,
    employee_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> bytes:
    """Same scope/filters as ``app.routes.leave.list_requests`` — see
    ``exports.leave_csv``'s docstring on the optional ``start``/``end``
    narrowing.
    """
    names = _employee_names(scope)
    leave_type_names = {lt.id: lt.name for lt in leave_service.list_leave_types(scope)}
    covers = None
    if start is not None and end is not None:
        tz = scheduling_service.organization_timezone(scope)
        covers = (
            datetime.combine(start, dt_time.min, tzinfo=tz),
            datetime.combine(end, dt_time.max, tzinfo=tz),
        )
    requests = leave_service.list_leave_requests(
        scope, status=status, employee_id=employee_id, covers=covers
    )
    header = ["Employee", "Leave type", "Start", "End", "Status"]
    rows = [
        [
            names.get(request.employee_id, f"#{request.employee_id}"),
            leave_type_names.get(request.leave_type_id, f"#{request.leave_type_id}"),
            request.starts_at.strftime("%Y-%m-%d %H:%M"),
            request.ends_at.strftime("%Y-%m-%d %H:%M"),
            request.status,
        ]
        for request in requests
    ]
    subtitle = f"{start.isoformat()} to {end.isoformat()}" if covers else "All leave requests"
    return _render("Leave Report", scope.organization_id, subtitle, header, rows)


def labor_cost_pdf(scope: AccessScope, department_id: int, start: date, end: date) -> bytes:
    """Aggregate only — see ``exports.labor_cost_csv``'s docstring on
    rule A4; never a per-employee figure.
    """
    department = get_scoped_or_404(Department, department_id, scope)
    summary = labor_cost_service.department_cost_summary(scope, department.id, start, end)
    header = ["Department", "Total cost", "Unconfigured employees"]
    rows = [[department.name, f"{summary.total:.2f}", summary.unconfigured_employee_count]]
    return _render(
        "Labor Cost Summary",
        scope.organization_id,
        f"{start.isoformat()} to {end.isoformat()}",
        header,
        rows,
    )


def admin_labor_cost_pdf(scope: AccessScope, employee_id: int, start: date, end: date) -> bytes:
    """Admin-only, single-employee payroll breakdown — see
    ``exports.admin_labor_cost_csv``'s docstring; the same restriction
    and scope this mirrors (``routes.labor_cost.employee_detail``'s
    ``role_required("admin")``, one employee at a time) is enforced here
    too, not only by the route.
    """
    if scope.role != "admin":
        abort(403)

    employee = employee_service.get_employee(scope, employee_id)
    line_items = labor_cost_service.range_cost_for_employee(scope, employee.id, start, end)
    header = ["Date", "Category", "Hours", "Rate", "Cost"]
    rows = [
        [
            item.business_date.isoformat(),
            item.category,
            f"{item.hours:.2f}",
            f"{item.rate:.2f}",
            f"{item.cost:.2f}",
        ]
        for item in line_items
    ]
    return _render(
        "Labor Cost — Payroll Detail",
        scope.organization_id,
        f"{employee.first_name} {employee.last_name} · {start.isoformat()} to {end.isoformat()}",
        header,
        rows,
    )
