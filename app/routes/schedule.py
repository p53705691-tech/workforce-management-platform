"""Schedule routes: list, create, update, assign, publish, cancel shifts.

Every view builds an ``AccessScope`` from the signed-in user and delegates
all authorization and data access to ``app.services.scheduling`` — no
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
from app.forms import AssignEmployeeForm, ShiftCreateForm, ShiftUpdateForm
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services.errors import ValidationError

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

# Default visible window for the list view when no ?start=/&end= query
# params are given: today through six days out, i.e. "this week".
_DEFAULT_WINDOW_DAYS = 6


def _default_date_range(scope) -> tuple[date, date]:
    # Round B fix: the org's own local date (rule A1), not the server's —
    # matches app.routes.dashboard's already-correct pattern. A server in
    # UTC and an org in, say, Pacific/Auckland disagree about "today" for
    # roughly half of every day; using date.today() here made this
    # module's default window silently drift from the dashboard's.
    today = report_service.today_business_date(scope)
    return today, today + timedelta(days=_DEFAULT_WINDOW_DAYS)


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _clean_optional(value):
    value = (value or "").strip()
    return value or None


def _shift_create_fields(form: ShiftCreateForm) -> dict:
    return {
        "department_id": form.department_id.data,
        "starts_at": form.starts_at.data,
        "ends_at": form.ends_at.data,
        "break_minutes": form.break_minutes.data or 0,
        # 0 is the form's "unassigned" sentinel (see app.forms.ShiftCreateForm).
        "employee_id": form.employee_id.data or None,
        "notes": _clean_optional(form.notes.data),
    }


def _shift_update_fields(form: ShiftUpdateForm) -> dict:
    return {
        "department_id": form.department_id.data,
        "starts_at": form.starts_at.data,
        "ends_at": form.ends_at.data,
        "break_minutes": form.break_minutes.data or 0,
        "notes": _clean_optional(form.notes.data),
    }


def _employee_choices(employees) -> list[tuple[int, str]]:
    return [(e.id, f"{e.first_name} {e.last_name}") for e in employees]


def _local(value, tz):
    """Render a stored (UTC-normalized) timestamptz as organization-local
    wall-clock time, matching what a manager originally typed in.
    """
    return value.astimezone(tz) if value is not None else None


@schedule_bp.route("", methods=["GET"])
@login_required
def list_shifts():
    scope = build_scope_for_user(current_user)
    default_start, default_end = _default_date_range(scope)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    department_id = request.args.get("department_id", type=int)

    shifts = scheduling_service.list_shifts(scope, start, end, department_id=department_id)
    departments = department_service.list_departments(scope)
    department_names = {d.id: d.name for d in departments}

    can_manage = scope.role in ("admin", "manager")
    tz = scheduling_service.organization_timezone(scope)
    employee_names = {}
    create_form = None
    edit_forms = {}
    assign_forms = {}

    if can_manage:
        employees = employee_service.list_employees(scope)
        employee_names = {e.id: f"{e.first_name} {e.last_name}" for e in employees}
        department_choices = [(d.id, d.name) for d in departments]
        employee_choices = _employee_choices(employees)

        create_form = ShiftCreateForm()
        create_form.department_id.choices = department_choices
        create_form.employee_id.choices = [(0, "Unassigned")] + employee_choices

        for shift in shifts:
            if shift.status == "draft":
                edit_form = ShiftUpdateForm(
                    department_id=shift.department_id,
                    starts_at=_local(shift.starts_at, tz),
                    ends_at=_local(shift.ends_at, tz),
                    break_minutes=shift.break_minutes,
                    notes=shift.notes,
                )
                edit_form.department_id.choices = department_choices
                edit_forms[shift.id] = edit_form

            if shift.status != "cancelled":
                assign_form = AssignEmployeeForm(employee_id=shift.employee_id)
                assign_form.employee_id.choices = employee_choices
                assign_forms[shift.id] = assign_form

    return render_template(
        "schedule/list.html",
        shifts=shifts,
        start=start,
        end=end,
        department_names=department_names,
        employee_names=employee_names,
        can_manage=can_manage,
        create_form=create_form,
        edit_forms=edit_forms,
        assign_forms=assign_forms,
        tz=scheduling_service.organization_timezone(scope),
    )


@schedule_bp.route("", methods=["POST"])
@role_required("admin", "manager")
def create_shift():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)
    employees = employee_service.list_employees(scope)

    form = ShiftCreateForm()
    form.department_id.choices = [(d.id, d.name) for d in departments]
    form.employee_id.choices = [(0, "Unassigned")] + _employee_choices(employees)

    if form.validate_on_submit():
        try:
            scheduling_service.create_shift(scope, **_shift_create_fields(form))
            flash("Shift created.", "success")
            return redirect(url_for("schedule.list_shifts"))
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Shift could not be created: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("schedule.list_shifts"))


@schedule_bp.route("/<int:shift_id>", methods=["POST"])
@role_required("admin", "manager")
def update_shift(shift_id):
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)

    form = ShiftUpdateForm()
    form.department_id.choices = [(d.id, d.name) for d in departments]

    if form.validate_on_submit():
        try:
            scheduling_service.update_shift(
                scope, shift_id, **_shift_update_fields(form)
            )
            flash("Shift updated.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Shift could not be updated: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("schedule.list_shifts"))


@schedule_bp.route("/<int:shift_id>/assign", methods=["POST"])
@role_required("admin", "manager")
def assign_shift(shift_id):
    scope = build_scope_for_user(current_user)
    employees = employee_service.list_employees(scope)

    form = AssignEmployeeForm()
    form.employee_id.choices = _employee_choices(employees)

    if form.validate_on_submit():
        try:
            scheduling_service.assign_employee(scope, shift_id, form.employee_id.data)
            flash("Employee assigned.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Could not assign employee: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("Please select a valid employee.", "error")

    return redirect(url_for("schedule.list_shifts"))


@schedule_bp.route("/<int:shift_id>/publish", methods=["POST"])
@role_required("admin", "manager")
def publish_shift(shift_id):
    scope = build_scope_for_user(current_user)
    try:
        scheduling_service.publish_shift(scope, shift_id)
        flash("Shift published.", "success")
    except ValidationError as error:
        flash(error.message, "error")

    return redirect(url_for("schedule.list_shifts"))


@schedule_bp.route("/<int:shift_id>/cancel", methods=["POST"])
@role_required("admin", "manager")
def cancel_shift(shift_id):
    scope = build_scope_for_user(current_user)
    try:
        scheduling_service.cancel_shift(scope, shift_id)
        flash("Shift cancelled.", "success")
    except ValidationError as error:
        flash(error.message, "error")

    return redirect(url_for("schedule.list_shifts"))
