"""DB-level constraint coverage for the ``shifts`` table.

These exercise constraints directly against the model (bypassing the
service layer) to confirm the database itself — not just application
code — protects these invariants. The overlap-prevention exclusion
constraint is the single most important test in this milestone: it is
the actual authority the service layer's pre-checks merely anticipate.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.shift import Shift
from tests.factories import make_department, make_employee, make_organization, make_shift, make_user

pytestmark = pytest.mark.integration


def _shift_kwargs(org, department, employee, created_by, **overrides):
    defaults = {
        "organization_id": org.id,
        "department_id": department.id,
        "employee_id": employee.id if employee else None,
        "starts_at": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        "ends_at": datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        "business_date": date(2026, 1, 1),
        "break_minutes": 0,
        "status": "draft",
        "created_by_user_id": created_by.id,
    }
    defaults.update(overrides)
    return defaults


def test_exclusion_constraint_rejects_overlapping_shift_for_same_employee(db_session):
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

    overlapping = Shift(
        **_shift_kwargs(
            org,
            department,
            employee,
            admin,
            starts_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 1),
        )
    )
    db_session.add(overlapping)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_non_overlapping_shifts_for_same_employee_are_allowed(db_session):
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

    later = Shift(
        **_shift_kwargs(
            org,
            department,
            employee,
            admin,
            starts_at=datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 1),
        )
    )
    db_session.add(later)

    db_session.flush()  # must not raise


def test_cancelled_shift_does_not_block_a_new_overlapping_shift(db_session):
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

    overlapping = Shift(
        **_shift_kwargs(
            org,
            department,
            employee,
            admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 1),
        )
    )
    db_session.add(overlapping)

    db_session.flush()  # must not raise: the existing shift is cancelled


def test_unassigned_shifts_may_overlap(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=None,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    other_open_shift = Shift(
        **_shift_kwargs(
            org,
            department,
            None,
            admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 1),
        )
    )
    db_session.add(other_open_shift)

    db_session.flush()  # must not raise: unassigned shifts don't compete


def test_overnight_shift_is_stored_as_a_single_row_with_start_date_attribution(
    db_session,
):
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
        starts_at=datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 2, 6, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    db_session.flush()
    fetched = db_session.get(Shift, shift.id)
    assert fetched is not None
    assert fetched.starts_at.hour == 22
    assert fetched.ends_at.day == 2
    assert fetched.business_date == date(2026, 1, 1)
    assert db_session.query(Shift).filter(Shift.employee_id == employee.id).count() == 1


def test_ends_at_before_starts_at_is_rejected(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    shift = Shift(
        **_shift_kwargs(
            org,
            department,
            None,
            admin,
            starts_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(shift)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_break_minutes_greater_than_or_equal_to_duration_is_rejected(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    # An 8-hour shift (480 minutes) with an 8-hour break leaves zero
    # working time — the break may not consume the entire shift.
    shift = Shift(
        **_shift_kwargs(
            org,
            department,
            None,
            admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            break_minutes=480,
        )
    )
    db_session.add(shift)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_shift_longer_than_24_hours_is_rejected(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    shift = Shift(
        **_shift_kwargs(
            org,
            department,
            None,
            admin,
            starts_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(shift)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_published_status_requires_published_at(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    shift = Shift(
        **_shift_kwargs(
            org, department, employee, admin, status="published", published_at=None
        )
    )
    db_session.add(shift)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_department_id_must_belong_to_the_same_organization(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    department_in_org_b = make_department(db_session, organization=org_b)
    admin = make_user(db_session, organization=org_a, role="admin")

    shift = Shift(
        **_shift_kwargs(org_a, department_in_org_b, None, admin)
    )
    db_session.add(shift)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
