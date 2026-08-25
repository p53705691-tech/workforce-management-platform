"""Integration tests for app.services.availability — read-only overlap checks."""

from datetime import date, datetime, timezone

import pytest

from app.auth.scope import AccessScope
from app.services import availability
from tests.factories import (
    make_department,
    make_employee,
    make_leave_request,
    make_leave_type,
    make_organization,
    make_shift,
    make_user,
)

pytestmark = pytest.mark.integration


def _scope(organization_id):
    return AccessScope(
        user_id=1,
        organization_id=organization_id,
        role="admin",
        department_ids=frozenset(),
        employee_id=None,
    )


def test_shifts_overlapping_finds_an_overlapping_active_shift(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    results = availability.shifts_overlapping(
        _scope(org.id),
        employee.id,
        datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
    )

    assert [s.id for s in results] == [shift.id]


def test_shifts_overlapping_ignores_cancelled_shifts(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
        status="cancelled",
    )

    results = availability.shifts_overlapping(
        _scope(org.id),
        employee.id,
        datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
    )

    assert results == []


def test_shifts_overlapping_ignores_non_overlapping_shifts(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    results = availability.shifts_overlapping(
        _scope(org.id),
        employee.id,
        datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc),
    )

    assert results == []


def test_shifts_overlapping_excludes_the_given_shift_id(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    results = availability.shifts_overlapping(
        _scope(org.id),
        employee.id,
        datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        exclude_shift_id=shift.id,
    )

    assert results == []
