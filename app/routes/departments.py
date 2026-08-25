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
from app.services.errors import ValidationError

departments_bp = Blueprint("departments", __name__, url_prefix="/departments")


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
        department.id: DepartmentForm(obj=department, prefix=f"edit-{department.id}-")
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
        form=form,
        edit_forms=_edit_forms_for(scope, departments),
    )


@departments_bp.route("/<int:department_id>", methods=["POST"])
@role_required("admin")
def update_department(department_id):
    scope = build_scope_for_user(current_user)
    form = DepartmentForm()

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
