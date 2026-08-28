"""Organization service: admin-only settings.

Currently just the one setting this hardening pass adds
(``location_validation_mode``) — kept as its own module rather than
folded into an existing service since "the organization's own settings"
is a distinct concern from any single domain area (attendance,
scheduling, ...).
"""

from flask import abort

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.organization import LOCATION_VALIDATION_MODES, Organization
from app.services import audit as audit_service
from app.services.errors import ValidationError


def get_organization(scope: AccessScope) -> Organization:
    return db.session.get(Organization, scope.organization_id)


def set_location_validation_mode(scope: AccessScope, mode: str) -> Organization:
    """Change the organization's clock-in/out location-validation mode.
    Admin only — this affects every employee's ability to clock in/out,
    not a single department's own configuration.
    """
    if scope.role != "admin":
        abort(403)

    if mode not in LOCATION_VALIDATION_MODES:
        raise ValidationError(
            "Not a valid location validation mode.", field="location_validation_mode"
        )

    organization = get_organization(scope)
    previous_mode = organization.location_validation_mode
    organization.location_validation_mode = mode
    audit_service.record(
        "organization_location_validation_mode_changed",
        "organization",
        entity_id=organization.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"from": previous_mode, "to": mode},
    )
    # One commit covers both the setting change and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()
    return organization
