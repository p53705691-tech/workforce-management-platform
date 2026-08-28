"""Job location service: admin-only management of named sites used by
the MULTI_SITE / SHIFT_JOB_LOCATION clock-in validation modes (see
app.models.organization). A shift is pinned to one of these via
app.services.scheduling (job_location_id), not here — this module only
manages the catalog of sites themselves.
"""

from decimal import Decimal

from flask import abort

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.job_location import JobLocation
from app.services import audit as audit_service
from app.services.errors import ValidationError


def list_job_locations(scope: AccessScope) -> list[JobLocation]:
    return (
        db.session.query(JobLocation)
        .filter(JobLocation.organization_id == scope.organization_id)
        .order_by(JobLocation.name)
        .all()
    )


def create_job_location(
    scope: AccessScope, name: str, latitude: Decimal, longitude: Decimal, radius_meters: int
) -> JobLocation:
    if scope.role != "admin":
        abort(403)

    if not name or not name.strip():
        raise ValidationError("Name is required.", field="name")
    if radius_meters <= 0:
        raise ValidationError("Radius must be greater than zero.", field="radius_meters")

    job_location = JobLocation(
        organization_id=scope.organization_id,
        name=name.strip(),
        latitude=latitude,
        longitude=longitude,
        radius_meters=radius_meters,
    )
    db.session.add(job_location)
    db.session.flush()
    audit_service.record(
        "job_location_created",
        "job_location",
        entity_id=job_location.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"name": job_location.name},
    )
    # One commit covers both the insert and the audit entry above — see
    # app.services.audit's module docstring.
    db.session.commit()
    return job_location
