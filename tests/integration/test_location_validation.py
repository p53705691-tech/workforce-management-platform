"""Clock-in/out location validation (app.services.location, wired into
app.services.attendance.clock_in/clock_out) — the client's three
businesses (taxi/barbershop/cleaning) map to NONE/MOBILE, FIXED_SITE,
and MULTI_SITE/SHIFT_JOB_LOCATION respectively (see
app.models.organization's module docstring for the full enum).
"""

from decimal import Decimal

import pytest

from app.auth.scope import AccessScope
from app.models.attendance_entry import AttendanceEntry
from app.services.attendance import clock_in
from app.services.errors import ValidationError
from tests.factories import make_department, make_employee, make_job_location, make_organization, make_shift, make_user

pytestmark = pytest.mark.integration


def _employee_scope(organization, employee, user):
    return AccessScope(
        user_id=user.id,
        organization_id=organization.id,
        role="employee",
        department_ids=frozenset(),
        employee_id=employee.id,
    )


class TestDefaultModeNeverValidates:
    def test_none_mode_clock_in_succeeds_with_no_location(self, db_session):
        """Default mode — a taxi organization with no location feature
        enabled must never be forced through a geofence.
        """
        org = make_organization(db_session)
        assert org.location_validation_mode == "NONE"
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        entry = clock_in(scope)

        assert entry.status == "open"
        assert entry.latitude is None

    def test_mobile_mode_never_validates_even_with_department_coordinates(self, db_session):
        org = make_organization(db_session, location_validation_mode="MOBILE")
        department = make_department(
            db_session, organization=org, latitude=Decimal("10"), longitude=Decimal("10"), radius_meters=50
        )
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        entry = clock_in(scope)

        assert entry.status == "open"


class TestFixedSiteMode:
    def test_rejects_clock_in_with_no_location(self, db_session):
        org = make_organization(db_session, location_validation_mode="FIXED_SITE")
        department = make_department(
            db_session, organization=org, latitude=Decimal("10"), longitude=Decimal("10"), radius_meters=100
        )
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        with pytest.raises(ValidationError):
            clock_in(scope)

    def test_rejects_clock_in_too_far_from_department(self, db_session):
        org = make_organization(db_session, location_validation_mode="FIXED_SITE")
        department = make_department(
            db_session, organization=org, latitude=Decimal("10"), longitude=Decimal("10"), radius_meters=100
        )
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        with pytest.raises(ValidationError):
            clock_in(scope, latitude=50.0, longitude=60.0)

    def test_accepts_clock_in_within_radius(self, db_session):
        org = make_organization(db_session, location_validation_mode="FIXED_SITE")
        department = make_department(
            db_session, organization=org, latitude=Decimal("10"), longitude=Decimal("10"), radius_meters=200
        )
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        # A tiny offset (~11m at this latitude) stays well within a
        # 200m radius.
        entry = clock_in(scope, latitude=10.0001, longitude=10.0001)

        assert entry.status == "open"
        assert float(entry.latitude) == pytest.approx(10.0001)

    def test_department_with_no_coordinates_configured_is_not_validated(self, db_session):
        """FIXED_SITE mode is organization-wide, but a department opts in
        by having coordinates set — an org can enable the mode and
        configure branches one at a time without instantly blocking
        every not-yet-configured department.
        """
        org = make_organization(db_session, location_validation_mode="FIXED_SITE")
        department = make_department(db_session, organization=org)
        assert department.latitude is None
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        entry = clock_in(scope)

        assert entry.status == "open"


class TestMultiSiteMode:
    def test_unscheduled_clock_in_is_never_blocked(self, db_session):
        """Mirrors attendance._match_shift's "no unambiguous shift ->
        don't guess" precedent: no matched shift means no known job
        location to validate against.
        """
        org = make_organization(db_session, location_validation_mode="MULTI_SITE")
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        scope = _employee_scope(org, employee, user)

        entry = clock_in(scope)

        assert entry.status == "open"

    def test_rejects_clock_in_too_far_from_matched_shifts_job_location(self, db_session):
        from datetime import datetime, timedelta, timezone

        org = make_organization(db_session, location_validation_mode="MULTI_SITE")
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        job_location = make_job_location(
            db_session, organization=org, latitude=Decimal("10"), longitude=Decimal("10"), radius_meters=100
        )
        now = datetime.now(timezone.utc)
        make_shift(
            db_session,
            organization=org,
            department=department,
            employee=employee,
            status="published",
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=4),
            published_at=now,
            job_location_id=job_location.id,
        )
        scope = _employee_scope(org, employee, user)

        with pytest.raises(ValidationError):
            clock_in(scope, latitude=50.0, longitude=60.0)

    def test_accepts_clock_in_within_matched_shifts_job_location(self, db_session):
        from datetime import datetime, timedelta, timezone

        org = make_organization(db_session, location_validation_mode="MULTI_SITE")
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
        job_location = make_job_location(
            db_session, organization=org, latitude=Decimal("10"), longitude=Decimal("10"), radius_meters=200
        )
        now = datetime.now(timezone.utc)
        make_shift(
            db_session,
            organization=org,
            department=department,
            employee=employee,
            status="published",
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=4),
            published_at=now,
            job_location_id=job_location.id,
        )
        scope = _employee_scope(org, employee, user)

        entry = clock_in(scope, latitude=10.0001, longitude=10.0001)

        assert entry.status == "open"
