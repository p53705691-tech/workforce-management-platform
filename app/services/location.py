"""Clock-in/out location validation — entirely opt-in per organization.

See ``app.models.organization``'s module docstring for the full
``location_validation_mode`` enum and what each value means for the
client's three businesses (taxi/barbershop/cleaning). This module is the
one place that enum is actually interpreted; ``app.services.attendance``
calls ``validate_clock_in_location`` and nothing else here.

No continuous tracking anywhere in this codebase: a location is only
ever read at the exact instant of a clock-in/out call, never polled or
stored on any schedule (per the client's explicit constraint).
"""

import math

from app.extensions import db
from app.models.department import Department
from app.models.job_location import JobLocation
from app.models.organization import Organization
from app.models.shift import Shift
from app.services.errors import ValidationError

_EARTH_RADIUS_METERS = 6_371_000


def _distance_meters(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance between two lat/lon points, in meters.

    Standard haversine formula — accurate enough for a geofence radius
    check (meters to low kilometers), which is the only thing this is
    ever used for; no need for a more precise (and heavier) ellipsoidal
    model at this scale.
    """
    lat1_rad, lat2_rad = math.radians(float(lat1)), math.radians(float(lat2))
    delta_lat = math.radians(float(lat2) - float(lat1))
    delta_lon = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return _EARTH_RADIUS_METERS * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def validate_clock_in_location(
    organization_id: int,
    department_id: int,
    shift_id: int | None,
    latitude,
    longitude,
) -> None:
    """Enforce ``Organization.location_validation_mode`` for one
    clock-in/out. Raises ``ValidationError`` if the location fails the
    check; returns normally (does nothing) whenever no check applies.

    - ``NONE``/``MOBILE``: never validates — a mobile workforce (taxi)
      must never be forced through a geofence.
    - ``FIXED_SITE``: the employee's own department must have
      coordinates/radius configured (an admin opts a department in by
      setting them — see ``app.models.department``); the clock-in must
      be within that radius. A department with no coordinates
      configured is treated the same as ``NONE`` for that department —
      an org can turn the mode on organization-wide and configure
      branches one at a time without instantly blocking every
      unconfigured department.
    - ``MULTI_SITE``/``SHIFT_JOB_LOCATION``: validated against the
      matched shift's ``job_location``, if any. An unmatched/unscheduled
      clock-in is never blocked — mirrors
      ``attendance._match_shift``'s existing "no single unambiguous
      shift matched -> don't guess" precedent, since there is no
      candidate location to validate against.
    """
    organization = db.session.get(Organization, organization_id)
    mode = organization.location_validation_mode

    if mode in ("NONE", "MOBILE"):
        return

    if mode == "FIXED_SITE":
        department = db.session.get(Department, department_id)
        if department.latitude is None:
            return
        if latitude is None or longitude is None:
            raise ValidationError(
                "This organization requires your location to clock in or out. "
                "Enable location access and try again.",
                field="latitude",
            )
        distance = _distance_meters(
            latitude, longitude, department.latitude, department.longitude
        )
        if distance > department.radius_meters:
            raise ValidationError(
                "You are too far from your department's location to clock "
                "in or out.",
                field="latitude",
            )
        return

    # MULTI_SITE / SHIFT_JOB_LOCATION
    if shift_id is None:
        return

    shift = db.session.get(Shift, shift_id)
    if shift is None or shift.job_location_id is None:
        return
    job_location = db.session.get(JobLocation, shift.job_location_id)
    if latitude is None or longitude is None:
        raise ValidationError(
            "This shift requires your location to clock in or out. Enable "
            "location access and try again.",
            field="latitude",
        )
    distance = _distance_meters(latitude, longitude, job_location.latitude, job_location.longitude)
    if distance > job_location.radius_meters:
        raise ValidationError(
            "You are too far from this shift's job location to clock in or out.",
            field="latitude",
        )
