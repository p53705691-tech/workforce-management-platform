"""Leave routes: list, request, approve, reject, cancel.

Every view builds an ``AccessScope`` from the signed-in user and delegates
all authorization and data access to ``app.services.leave`` — no route
here queries the database directly. Form data is read field by field into
an explicit dict before being passed to the service; raw ``request.form``
is never forwarded, so a client cannot smuggle in a field (e.g.
``organization_id``) that was never part of the form.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.auth.decorators import login_required, role_required
from app.auth.scope import build_scope_for_user
from app.extensions import db
from app.forms import (
    AdminLeaveRequestForm,
    ApproveLeaveForm,
    CancelLeaveForm,
    LeaveRequestForm,
    RejectLeaveForm,
)
from app.services import employees as employee_service
from app.services import leave as leave_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services.errors import ValidationError

leave_bp = Blueprint("leave", __name__, url_prefix="/leave")


def _clean_optional(value):
    value = (value or "").strip()
    return value or None


def _leave_request_fields(form) -> dict:
    fields = {
        "leave_type_id": form.leave_type_id.data,
        "starts_at": form.starts_at.data,
        "ends_at": form.ends_at.data,
        "reason": _clean_optional(form.reason.data),
    }
    if hasattr(form, "employee_id"):
        # 0 is the form's "myself" sentinel (see app.forms.AdminLeaveRequestForm).
        fields["employee_id"] = form.employee_id.data or None
    return fields


@leave_bp.route("", methods=["GET"])
@login_required
def list_requests():
    scope = build_scope_for_user(current_user)
    status = request.args.get("status") or None
    can_manage = scope.role in ("admin", "manager")
    employee_id = request.args.get("employee_id", type=int) if can_manage else None
    tz = scheduling_service.organization_timezone(scope)

    requests = leave_service.list_leave_requests(scope, status=status, employee_id=employee_id)
    leave_types = leave_service.list_leave_types(scope)
    leave_type_names = {lt.id: lt.name for lt in leave_types}

    employee_names = {}
    employee_choices = []
    conflicts = {}
    approve_forms = {}
    reject_forms = {}
    cancel_forms = {}
    leave_timing = {}

    # Submitting a leave request is employee self-service only — an
    # admin/manager's Leave page is a review/approval surface, not a
    # place to file a request "as" someone (see app.forms.LeaveRequestForm
    # vs. AdminLeaveRequestForm; the latter still backs the POST route
    # directly, for callers that reach it without this page).
    if can_manage:
        employees = employee_service.list_employees(scope)
        employee_names = {e.id: f"{e.first_name} {e.last_name}" for e in employees}
        employee_choices = sorted(employee_names.items(), key=lambda pair: pair[1])
        request_form = None
    else:
        request_form = LeaveRequestForm()
        request_form.leave_type_id.choices = [(lt.id, lt.name) for lt in leave_types]

    # Self-service only: "is this approved leave happening now, or coming
    # up" is display-only sugar for the employee's own My Leave page — no
    # new leave rule, just a same-day/future comparison of dates the
    # request already carries, mirroring how reports.who_is_on_leave_today
    # compares a range against today elsewhere.
    if not can_manage:
        today = report_service.today_business_date(scope)
        for leave_request in requests:
            if leave_request.status != "approved":
                continue
            start_date = leave_request.starts_at.astimezone(tz).date()
            end_date = leave_request.ends_at.astimezone(tz).date()
            if start_date <= today <= end_date:
                leave_timing[leave_request.id] = "current"
            elif start_date > today:
                leave_timing[leave_request.id] = "upcoming"

    for leave_request in requests:
        if leave_request.status == "pending":
            if can_manage:
                conflicts[leave_request.id] = leave_service.conflicting_shifts_for(
                    scope, leave_request
                )
                approve_forms[leave_request.id] = ApproveLeaveForm()
                reject_forms[leave_request.id] = RejectLeaveForm()

        is_owner = (
            scope.role == "employee" and scope.employee_id == leave_request.employee_id
        )
        cancellable = leave_request.status in ("pending", "approved") and (
            can_manage or (is_owner and leave_request.status == "pending")
        )
        if cancellable:
            cancel_forms[leave_request.id] = CancelLeaveForm()

    # Employee gets a personal, status-summary composition of the exact
    # same scoped requests (no separate query) — per MVP-1_version2.md
    # §17, not the admin/manager approval-focused table (which an
    # employee never gets approve/reject controls for anyway, but the
    # dense multi-employee layout doesn't fit a self-service view).
    template = "leave/my_leave.html" if scope.role == "employee" else "leave/list.html"

    return render_template(
        template,
        requests=requests,
        leave_type_names=leave_type_names,
        employee_names=employee_names,
        employee_choices=employee_choices,
        selected_employee_id=employee_id,
        conflicts=conflicts,
        can_manage=can_manage,
        request_form=request_form,
        approve_forms=approve_forms,
        reject_forms=reject_forms,
        cancel_forms=cancel_forms,
        leave_timing=leave_timing,
        status=status,
        tz=tz,
    )


@leave_bp.route("", methods=["POST"])
@login_required
def request_leave():
    scope = build_scope_for_user(current_user)
    can_manage = scope.role in ("admin", "manager")
    form = AdminLeaveRequestForm() if can_manage else LeaveRequestForm()
    leave_types = leave_service.list_leave_types(scope)
    form.leave_type_id.choices = [(lt.id, lt.name) for lt in leave_types]

    if can_manage:
        employees = employee_service.list_employees(scope)
        form.employee_id.choices = [(0, "Myself")] + [
            (e.id, f"{e.first_name} {e.last_name}") for e in employees
        ]

    if form.validate_on_submit():
        try:
            leave_service.request_leave(scope, **_leave_request_fields(form))
            flash("Leave request submitted.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash(
                "Could not submit leave request: a value conflicts with an "
                "existing record.",
                "error",
            )
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("leave.list_requests"))


@leave_bp.route("/<int:leave_request_id>/approve", methods=["POST"])
@role_required("admin", "manager")
def approve_leave(leave_request_id):
    scope = build_scope_for_user(current_user)
    form = ApproveLeaveForm()

    if form.validate_on_submit():
        try:
            leave_service.approve_leave(
                scope, leave_request_id, decision_note=_clean_optional(form.decision_note.data)
            )
            flash("Leave request approved.", "success")
        except ValidationError as error:
            flash(error.message, "error")
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("leave.list_requests"))


@leave_bp.route("/<int:leave_request_id>/reject", methods=["POST"])
@role_required("admin", "manager")
def reject_leave(leave_request_id):
    scope = build_scope_for_user(current_user)
    form = RejectLeaveForm()

    if form.validate_on_submit():
        try:
            leave_service.reject_leave(
                scope, leave_request_id, decision_note=form.decision_note.data.strip()
            )
            flash("Leave request rejected.", "success")
        except ValidationError as error:
            flash(error.message, "error")
    else:
        flash("A reason is required to reject a leave request.", "error")

    return redirect(url_for("leave.list_requests"))


@leave_bp.route("/<int:leave_request_id>/cancel", methods=["POST"])
@login_required
def cancel_leave(leave_request_id):
    scope = build_scope_for_user(current_user)
    form = CancelLeaveForm()

    if form.validate_on_submit():
        try:
            leave_service.cancel_leave(scope, leave_request_id)
            flash("Leave request cancelled.", "success")
        except ValidationError as error:
            flash(error.message, "error")
    else:
        flash("Please try again.", "error")

    return redirect(url_for("leave.list_requests"))
