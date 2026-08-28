"""Manager account routes: admin-only creation of manager logins and
department-manager assignment (see app.services.managers's module
docstring for why this didn't exist before this pass).
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.auth.decorators import role_required
from app.auth.scope import build_scope_for_user
from app.forms import AssignDepartmentManagerForm, CreateManagerAccountForm
from app.services import departments as department_service
from app.services import managers as manager_service
from app.services.errors import ValidationError

managers_bp = Blueprint("managers", __name__, url_prefix="/managers")


@managers_bp.route("", methods=["GET"])
@role_required("admin")
def index():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)
    department_names = {department.id: department.name for department in departments}

    managers = manager_service.list_managers(scope)
    managed_departments = {
        manager.id: manager_service.managed_department_ids(scope, manager.id)
        for manager in managers
    }

    create_form = CreateManagerAccountForm()
    assign_form = AssignDepartmentManagerForm()
    assign_form.department_id.choices = [(d.id, d.name) for d in departments]

    return render_template(
        "managers/index.html",
        managers=managers,
        department_names=department_names,
        managed_departments=managed_departments,
        create_form=create_form,
        assign_form=assign_form,
    )


@managers_bp.route("", methods=["POST"])
@role_required("admin")
def create_manager():
    scope = build_scope_for_user(current_user)
    form = CreateManagerAccountForm()

    if form.validate_on_submit():
        try:
            manager_service.create_manager_account(
                scope, form.email.data.strip(), form.password.data
            )
            flash("Manager account created. Assign at least one department below.", "success")
        except ValidationError as error:
            flash(error.message, "error")
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("managers.index"))


@managers_bp.route("/<int:user_id>/departments", methods=["POST"])
@role_required("admin")
def assign_department(user_id):
    scope = build_scope_for_user(current_user)
    department_id = request.form.get("department_id", type=int)

    if department_id is None:
        flash("Select a department to assign.", "error")
        return redirect(url_for("managers.index"))

    try:
        manager_service.assign_department(scope, user_id, department_id)
        flash("Department assigned.", "success")
    except ValidationError as error:
        flash(error.message, "error")

    return redirect(url_for("managers.index"))


@managers_bp.route("/<int:user_id>/departments/<int:department_id>/remove", methods=["POST"])
@role_required("admin")
def unassign_department(user_id, department_id):
    scope = build_scope_for_user(current_user)
    manager_service.unassign_department(scope, user_id, department_id)
    flash("Department unassigned.", "success")
    return redirect(url_for("managers.index"))
