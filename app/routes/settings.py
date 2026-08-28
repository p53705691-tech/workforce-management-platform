"""Organization settings routes: clock-in/out location validation mode,
and the job-location catalog it can use (MULTI_SITE/SHIFT_JOB_LOCATION —
see app.models.organization). Admin only.
"""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.auth.decorators import role_required
from app.auth.scope import build_scope_for_user
from app.extensions import db
from app.forms import JobLocationForm, OrganizationSettingsForm
from app.models.organization import LOCATION_VALIDATION_MODES
from app.services import job_locations as job_location_service
from app.services import organizations as organization_service
from app.services.errors import ValidationError

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

_MODE_LABELS = {
    "NONE": "None — no location check",
    "FIXED_SITE": "Fixed site — within a department's configured radius",
    "MULTI_SITE": "Multiple sites — within the shift's assigned location",
    "MOBILE": "Mobile workforce — never checked",
    "SHIFT_JOB_LOCATION": "Per-shift job location — within the shift's assigned location",
}


@settings_bp.route("", methods=["GET"])
@role_required("admin")
def index():
    scope = build_scope_for_user(current_user)
    organization = organization_service.get_organization(scope)

    mode_form = OrganizationSettingsForm(location_validation_mode=organization.location_validation_mode)
    mode_form.location_validation_mode.choices = [
        (mode, _MODE_LABELS[mode]) for mode in LOCATION_VALIDATION_MODES
    ]
    job_location_form = JobLocationForm()

    return render_template(
        "settings/index.html",
        organization=organization,
        mode_form=mode_form,
        job_location_form=job_location_form,
        job_locations=job_location_service.list_job_locations(scope),
    )


@settings_bp.route("/location-mode", methods=["POST"])
@role_required("admin")
def update_location_mode():
    scope = build_scope_for_user(current_user)
    form = OrganizationSettingsForm()
    form.location_validation_mode.choices = [(mode, mode) for mode in LOCATION_VALIDATION_MODES]

    if form.validate_on_submit():
        try:
            organization_service.set_location_validation_mode(
                scope, form.location_validation_mode.data
            )
            flash("Location validation mode updated.", "success")
        except ValidationError as error:
            flash(error.message, "error")
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("settings.index"))


@settings_bp.route("/job-locations", methods=["POST"])
@role_required("admin")
def create_job_location():
    scope = build_scope_for_user(current_user)
    form = JobLocationForm()

    if form.validate_on_submit():
        try:
            job_location_service.create_job_location(
                scope,
                name=form.name.data,
                latitude=form.latitude.data,
                longitude=form.longitude.data,
                radius_meters=form.radius_meters.data,
            )
            flash("Job location added.", "success")
        except ValidationError as error:
            flash(error.message, "error")
        except IntegrityError:
            db.session.rollback()
            flash("Job location could not be added.", "error")
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("settings.index"))
