"""Employee routes: list, view, create, update, terminate.

Every view builds an ``AccessScope`` from the signed-in user and delegates
all authorization and data access to ``app.services.employees`` — no
route here queries the database directly. Form data is read field by
field into an explicit dict before being passed to the service; raw
``request.form`` is never forwarded, so a client cannot smuggle in a
field (e.g. ``organization_id``) that was never part of the form.
"""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.auth.decorators import login_required, role_required
from app.auth.scope import build_scope_for_user
from app.extensions import db
from app.forms import (
    EmployeeCreateForm,
    EmployeeUpdateForm,
    SetPayRateForm,
    TerminateEmployeeForm,
)
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services import pay_rates as pay_rate_service
from app.services.errors import ValidationError

employees_bp = Blueprint("employees", __name__, url_prefix="/employees")


def _clean_optional(value):
    value = (value or "").strip()
    return value or None


def _employee_create_fields(form: EmployeeCreateForm) -> dict:
    return {
        "department_id": form.department_id.data,
        "employee_number": form.employee_number.data.strip(),
        "first_name": form.first_name.data.strip(),
        "last_name": form.last_name.data.strip(),
        "email": _clean_optional(form.email.data),
        "phone": _clean_optional(form.phone.data),
        "employment_status": form.employment_status.data,
        "hired_on": form.hired_on.data,
        "weekly_contract_hours": form.weekly_contract_hours.data,
    }


def _employee_update_fields(form: EmployeeUpdateForm) -> dict:
    return {
        "department_id": form.department_id.data,
        "employee_number": form.employee_number.data.strip(),
        "first_name": form.first_name.data.strip(),
        "last_name": form.last_name.data.strip(),
        "email": _clean_optional(form.email.data),
        "phone": _clean_optional(form.phone.data),
        "employment_status": form.employment_status.data,
        "weekly_contract_hours": form.weekly_contract_hours.data,
    }


@employees_bp.route("", methods=["GET"])
@role_required("admin", "manager")
def list_employees():
    scope = build_scope_for_user(current_user)
    employees = employee_service.list_employees(scope)
    departments = department_service.list_departments(scope)
    department_names = {department.id: department.name for department in departments}

    form = None
    if scope.role == "admin":
        form = EmployeeCreateForm()
        form.department_id.choices = [(d.id, d.name) for d in departments]

    return render_template(
        "employees/list.html",
        employees=employees,
        department_names=department_names,
        form=form,
    )


@employees_bp.route("", methods=["POST"])
@role_required("admin")
def create_employee():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)

    form = EmployeeCreateForm()
    form.department_id.choices = [(d.id, d.name) for d in departments]

    if form.validate_on_submit():
        try:
            employee = employee_service.create_employee(
                scope, **_employee_create_fields(form)
            )
            flash("Employee created.", "success")
            return redirect(
                url_for("employees.get_employee", employee_id=employee.id)
            )
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Employee could not be created: a value conflicts with an "
                "existing record.",
                "error",
            )

    employees = employee_service.list_employees(scope)
    department_names = {department.id: department.name for department in departments}
    return render_template(
        "employees/list.html",
        employees=employees,
        department_names=department_names,
        form=form,
    )


@employees_bp.route("/<int:employee_id>", methods=["GET"])
@login_required
def get_employee(employee_id):
    scope = build_scope_for_user(current_user)
    employee = employee_service.get_employee(scope, employee_id)

    can_edit = scope.role == "admin" or (
        scope.role == "manager" and employee.department_id in scope.department_ids
    )

    edit_form = None
    departments = []
    if can_edit:
        departments = department_service.list_departments(scope)
        edit_form = EmployeeUpdateForm(obj=employee)
        edit_form.department_id.choices = [(d.id, d.name) for d in departments]

    terminate_form = TerminateEmployeeForm() if scope.role == "admin" else None
    department_names = {department.id: department.name for department in departments}

    return render_template(
        "employees/detail.html",
        employee=employee,
        can_edit=can_edit,
        edit_form=edit_form,
        terminate_form=terminate_form,
        department_names=department_names,
    )


@employees_bp.route("/<int:employee_id>", methods=["POST"])
@role_required("admin", "manager")
def update_employee(employee_id):
    scope = build_scope_for_user(current_user)
    # 404s here (via get_employee's scoped lookup) before any write is
    # attempted, so a manager probing another department's employee id
    # gets the same "not found" response as a genuinely missing row.
    employee_service.get_employee(scope, employee_id)

    departments = department_service.list_departments(scope)
    form = EmployeeUpdateForm()
    form.department_id.choices = [(d.id, d.name) for d in departments]

    if form.validate_on_submit():
        try:
            employee_service.update_employee(
                scope, employee_id, **_employee_update_fields(form)
            )
            flash("Employee updated.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Employee could not be updated: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("employees.get_employee", employee_id=employee_id))


@employees_bp.route("/<int:employee_id>/terminate", methods=["POST"])
@role_required("admin")
def terminate_employee(employee_id):
    scope = build_scope_for_user(current_user)
    # Confirms the employee is in scope (org-scoped 404) even though
    # role_required already restricts this route to admins.
    employee_service.get_employee(scope, employee_id)

    form = TerminateEmployeeForm()
    if form.validate_on_submit():
        try:
            employee_service.terminate_employee(
                scope, employee_id, form.terminated_on.data
            )
            flash("Employee terminated.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Employee could not be terminated due to a data constraint.",
                "error",
            )
    else:
        flash("Please provide a valid termination date.", "error")

    return redirect(url_for("employees.get_employee", employee_id=employee_id))


@employees_bp.route("/<int:employee_id>/pay-rate", methods=["GET"])
@role_required("admin")
def view_pay_rate(employee_id):
    """View an employee's hourly-rate history and the form to add a new
    rate period. Admin only — pay rates are more sensitive than the
    labor-cost totals a manager may see (confirmed rule A4), so this
    route never accepts a manager, unlike ``employees.get_employee``.
    """
    scope = build_scope_for_user(current_user)
    # Confirms the employee is in scope (org-scoped 404) even though
    # role_required already restricts this route to admins — same
    # defense-in-depth pattern as terminate_employee.
    employee = employee_service.get_employee(scope, employee_id)
    history = pay_rate_service.list_pay_rate_history(scope, employee_id)

    return render_template(
        "employees/pay_rate.html",
        employee=employee,
        history=history,
        form=SetPayRateForm(),
    )


@employees_bp.route("/<int:employee_id>/pay-rate", methods=["POST"])
@role_required("admin")
def set_pay_rate(employee_id):
    scope = build_scope_for_user(current_user)
    employee_service.get_employee(scope, employee_id)

    form = SetPayRateForm()
    if form.validate_on_submit():
        try:
            pay_rate_service.set_pay_rate(
                scope,
                employee_id,
                hourly_rate=form.hourly_rate.data,
                effective_from=form.effective_from.data,
                effective_to=form.effective_to.data,
            )
            flash("Pay rate saved.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Pay rate could not be saved: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("employees.view_pay_rate", employee_id=employee_id))
