"""Attendance routes: clock in, clock out, correct, list.

Every view builds an ``AccessScope`` from the signed-in user and delegates
all authorization and data access to ``app.services.attendance`` — no
route here queries the database directly. Form data is read field by
field into an explicit dict before being passed to the service; raw
``request.form`` is never forwarded, so a client cannot smuggle in a
field (e.g. ``organization_id``) that was never part of the form.
"""

from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.auth.decorators import login_required, role_required
from app.auth.scope import build_scope_for_user
from app.extensions import db
from app.forms import AdminClockInForm, AdminClockOutForm, ClockInForm, ClockOutForm, CorrectEntryForm
from app.services import attendance as attendance_service
from app.services import employees as employee_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services.errors import ValidationError

attendance_bp = Blueprint("attendance", __name__, url_prefix="/attendance")

# Default visible window for the list view when no ?start=/&end= query
# params are given: today through six days out, i.e. "this week" — same
# default as the schedule list view.
_DEFAULT_WINDOW_DAYS = 6


def _default_date_range(scope) -> tuple[date, date]:
    # Round B fix: org-local "today" (rule A1), not the server's — see
    # app.routes.schedule's identical fix for the full rationale.
    today = report_service.today_business_date(scope)
    return today, today + timedelta(days=_DEFAULT_WINDOW_DAYS)


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


# Widest date range this list view will query in one request, same bound
# (and same reasoning: an arbitrary, user-editable ?start=/&end= query
# string) as app.routes.dashboard's identical constant/helper. Without
# this, an authenticated admin/manager could request the organization's
# entire attendance history in one request, instantiating a WTForms
# CorrectEntryForm per returned row (security-review finding).
_MAX_LIST_RANGE_DAYS = 92


def _clamp_range(start: date, end: date) -> tuple[date, date]:
    if (end - start).days > _MAX_LIST_RANGE_DAYS:
        start = end - timedelta(days=_MAX_LIST_RANGE_DAYS)
    return start, end


@attendance_bp.route("", methods=["GET"])
@login_required
def list_entries():
    scope = build_scope_for_user(current_user)
    default_start, default_end = _default_date_range(scope)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    start, end = _clamp_range(start, end)
    employee_id = request.args.get("employee_id", type=int)

    can_manage = scope.role in ("admin", "manager")
    entries_context = report_service.attendance_entries_with_context(
        scope, start, end, employee_id=employee_id if can_manage else None
    )

    employee_names = {}
    employee_choices = []
    correct_forms = {}

    if can_manage:
        employees = employee_service.list_employees(scope)
        employee_names = {e.id: f"{e.first_name} {e.last_name}" for e in employees}
        employee_choices = sorted(employee_names.items(), key=lambda pair: pair[1])
        for row in entries_context:
            correct_forms[row["entry"].id] = CorrectEntryForm()

    # The status card is never shown for can_manage (see the template), so
    # this lookup only runs for a plain employee.
    attendance_status = None if can_manage else report_service.current_attendance_status(scope)

    can_clock_out = (
        not can_manage
        and bool(attendance_status)
        and attendance_status["entry"].status == "open"
    )
    status_clock_out_form = ClockOutForm() if can_clock_out else None

    # Employee gets a calmer, history-focused composition of the exact
    # same scoped data (no separate query) — per MVP-1_version2.md §15:
    # "show only the employee's own information," not the admin/manager
    # management surface with correction/employee-filter controls.
    template = "attendance/my_attendance.html" if scope.role == "employee" else "attendance/list.html"

    return render_template(
        template,
        entries_context=entries_context,
        start=start,
        end=end,
        employee_names=employee_names,
        employee_choices=employee_choices,
        selected_employee_id=employee_id,
        can_manage=can_manage,
        correct_forms=correct_forms,
        attendance_status=attendance_status,
        status_clock_out_form=status_clock_out_form,
        scheduled_hours=scheduling_service.scheduled_hours,
        tz=scheduling_service.organization_timezone(scope),
    )


@attendance_bp.route("/clock-in", methods=["POST"])
@login_required
def clock_in():
    scope = build_scope_for_user(current_user)
    can_manage = scope.role in ("admin", "manager")
    form = AdminClockInForm() if can_manage else ClockInForm()

    if can_manage:
        employees = employee_service.list_employees(scope)
        form.employee_id.choices = [(0, "Myself")] + [
            (e.id, f"{e.first_name} {e.last_name}") for e in employees
        ]

    if form.validate_on_submit():
        try:
            # 0 is the "myself" sentinel (see app.forms.AdminClockInForm);
            # neither field exists at all on the plain self-service form.
            employee_id = (form.employee_id.data or None) if can_manage else None
            at = form.at.data if can_manage else None
            attendance_service.clock_in(scope, employee_id=employee_id, at=at)
            flash("Clocked in.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Could not clock in: a value conflicts with an existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("attendance.list_entries"))


@attendance_bp.route("/<int:entry_id>/clock-out", methods=["POST"])
@login_required
def clock_out(entry_id):
    scope = build_scope_for_user(current_user)
    can_manage = scope.role in ("admin", "manager")
    form = AdminClockOutForm() if can_manage else ClockOutForm()

    if form.validate_on_submit():
        try:
            at = form.at.data if can_manage else None
            attendance_service.clock_out(scope, entry_id, at=at)
            flash("Clocked out.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Could not clock out: a value conflicts with an existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("attendance.list_entries"))


@attendance_bp.route("/<int:entry_id>/correct", methods=["POST"])
@role_required("admin", "manager")
def correct_entry(entry_id):
    scope = build_scope_for_user(current_user)
    form = CorrectEntryForm()

    if form.validate_on_submit():
        try:
            attendance_service.correct_entry(
                scope,
                entry_id,
                edit_reason=form.edit_reason.data.strip(),
                started_at=form.started_at.data,
                ended_at=form.ended_at.data,
                break_minutes=form.break_minutes.data,
            )
            flash("Attendance entry corrected.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Could not correct entry: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("A reason is required to correct an attendance entry.", "error")

    return redirect(url_for("attendance.list_entries"))
