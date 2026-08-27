"""Department routes: list, create, update, deactivate.

Every view builds an ``AccessScope`` from the signed-in user and delegates
all authorization and data access to ``app.services.departments`` — no
route here queries the database directly.
"""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.auth.decorators import role_required
from app.auth.scope import build_scope_for_user
from app.extensions import db
from app.forms import DepartmentForm
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services.errors import ValidationError

departments_bp = Blueprint("departments", __name__, url_prefix="/departments")


def _active_employee_counts(scope) -> dict:
    """Department id -> active employee headcount, for the directory's
    "how many people are in this department" column. Same "active"
    definition used across the app (dashboard's total_employees,
    scheduling.coverage_summary) — a terminated/inactive record isn't
    part of a department's current headcount. Composed here from the
    already-scoped employee list rather than a new service function:
    a one-line aggregation, not a reusable business rule.
    """
    counts: dict[int, int] = {}
    for employee in employee_service.list_employees(scope):
        if employee.employment_status == "active":
            counts[employee.department_id] = counts.get(employee.department_id, 0) + 1
    return counts


def _edit_forms_for(scope, departments) -> dict:
    """One pre-filled edit form per department, keyed by id. Admin only —
    managers never see an edit control (see the template).

    A distinct WTForms ``prefix`` per row keeps each form's field
    ids/CSRF field name unique on the page, same reason app.forms uses
    distinct classes for create vs. update elsewhere (e.g.
    ``EmployeeCreateForm``/``EmployeeUpdateForm``) rather than one shared
    form instance.
    """
    if scope.role != "admin":
        return {}
    return {
        # meta={"csrf": False}: this form's own CSRF field would render
        # as "edit-{id}-csrf_token" under its prefix, which the app's
        # global CSRFProtect (flask_wtf.CSRFProtect, checking the literal
        # field name "csrf_token") never finds — every real submission
        # of a prefixed edit form was rejected with 400 before reaching
        # this route at all. The template instead renders one plain,
        # unprefixed csrf_token input per row (same pattern the
        # Deactivate form on this page already uses), so CSRF protection
        # stays intact while only name/code stay row-prefixed.
        department.id: DepartmentForm(
            obj=department, prefix=f"edit-{department.id}-", meta={"csrf": False}
        )
        for department in departments
    }


@departments_bp.route("", methods=["GET"])
@role_required("admin", "manager")
def list_departments():
    scope = build_scope_for_user(current_user)
    departments = department_service.list_departments(scope)
    form = DepartmentForm() if scope.role == "admin" else None
    return render_template(
        "departments/list.html",
        departments=departments,
        employee_counts=_active_employee_counts(scope),
        form=form,
        edit_forms=_edit_forms_for(scope, departments),
    )


@departments_bp.route("", methods=["POST"])
@role_required("admin")
def create_department():
    scope = build_scope_for_user(current_user)
    form = DepartmentForm()

    if form.validate_on_submit():
        try:
            department_service.create_department(
                scope, name=form.name.data.strip(), code=form.code.data.strip()
            )
            flash("Department created.", "success")
            return redirect(url_for("departments.list_departments"))
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Department could not be created: name or code already in use.",
                "error",
            )

    departments = department_service.list_departments(scope)
    return render_template(
        "departments/list.html",
        departments=departments,
        employee_counts=_active_employee_counts(scope),
        form=form,
        edit_forms=_edit_forms_for(scope, departments),
    )


@departments_bp.route("/<int:department_id>", methods=["POST"])
@role_required("admin")
def update_department(department_id):
    scope = build_scope_for_user(current_user)
    # Must match the prefix/meta the row's edit form was rendered with
    # (_edit_forms_for) — see that function's comment for why csrf is
    # disabled on this row-scoped form instance specifically.
    form = DepartmentForm(prefix=f"edit-{department_id}-", meta={"csrf": False})

    if form.validate_on_submit():
        try:
            # department_service.update_department only accepts name/code
            # (see its _UPDATABLE_FIELDS) — a client attempting to smuggle
            # in e.g. organization_id or is_active via extra form fields
            # would raise ValidationError there, not silently apply here,
            # since only these two explicit keyword arguments are ever
            # forwarded.
            department_service.update_department(
                scope,
                department_id,
                name=form.name.data.strip(),
                code=form.code.data.strip(),
            )
            flash("Department updated.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Department could not be updated: name or code already in use.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("departments.list_departments"))


@departments_bp.route("/<int:department_id>/deactivate", methods=["POST"])
@role_required("admin")
def deactivate_department(department_id):
    scope = build_scope_for_user(current_user)
    department_service.deactivate_department(scope, department_id)
    flash("Department deactivated.", "success")
    return redirect(url_for("departments.list_departments"))


@departments_bp.route("/<int:department_id>/delete", methods=["POST"])
@role_required("admin")
def delete_department(department_id):
    scope = build_scope_for_user(current_user)
    try:
        department_service.delete_department(scope, department_id)
        flash("Department deleted.", "success")
    except ValidationError as error:
        flash(error.message, "error")
    return redirect(url_for("departments.list_departments"))
