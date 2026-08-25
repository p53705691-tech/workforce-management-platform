"""Route-level coverage for attendance endpoints.

Mirrors the authorization-focused style of test_schedule_routes.py.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.attendance_entry import AttendanceEntry
from app.models.department_manager import DepartmentManager
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
    make_user,
)

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def _make_manager(db_session, org, *managed_departments):
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    for department in managed_departments:
        db_session.add(
            DepartmentManager(
                user_id=manager.id, department_id=department.id, organization_id=org.id
            )
        )
    db_session.flush()
    return manager


def _make_employee_user(db_session, org, employee):
    return make_user(
        db_session, organization=org, role="employee", password=PASSWORD, employee_id=employee.id
    )


def test_clocking_in_twice_returns_a_clean_error_not_a_500(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    first_response = client.post("/attendance/clock-in", follow_redirects=True)
    assert first_response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 1

    second_response = client.post("/attendance/clock-in", follow_redirects=True)

    assert second_response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 1


def test_employee_cannot_clock_in_on_behalf_of_another_employee(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    # The self-service ClockInForm has no employee_id field at all, but
    # the route must not trust a client-forged one even if it's posted
    # directly (server remains authoritative, never a hidden UI concern).
    response = client.post(
        "/attendance/clock-in",
        data={"employee_id": str(other_employee.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200  # form has no such field, ignored
    assert db_session.query(AttendanceEntry).filter_by(employee_id=other_employee.id).count() == 0


def test_manager_can_clock_in_an_employee_in_a_managed_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/attendance/clock-in",
        data={"employee_id": str(employee.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 1


def test_manager_cannot_clock_in_an_employee_outside_their_managed_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=other_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/attendance/clock-in",
        data={"employee_id": str(employee.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 0


def test_employee_can_clock_out_their_own_open_entry(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        # Recent, not the factory's fixed 2024-01-01 default: clock_out
        # closes with real "now", and a fixed, long-past started_at would
        # otherwise violate Round B's duration_max_24_hours CHECK once
        # far enough from that date.
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        ended_at=None,
        status="open",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/attendance/{entry.id}/clock-out", follow_redirects=True)

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.status == "closed"


def test_employee_cannot_clock_out_another_employees_entry(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=other_employee,
        created_by=admin,
        ended_at=None,
        status="open",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/attendance/{entry.id}/clock-out")

    assert response.status_code == 404
    db_session.refresh(entry)
    assert entry.status == "open"


def test_employee_role_cannot_correct_an_attendance_entry(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"edit_reason": "Trying to change my own record"},
    )

    assert response.status_code == 403


def test_correct_entry_without_a_reason_is_rejected_at_the_route_level(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    _login(client, admin)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"break_minutes": "15"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.edited_by_user_id is None
    assert entry.edited_at is None
    assert entry.break_minutes == 0


def test_admin_can_correct_an_attendance_entry_with_a_reason(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    _login(client, admin)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"break_minutes": "15", "edit_reason": "Adjusted per timesheet review."},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.break_minutes == 15
    assert entry.edited_by_user_id == admin.id
    assert entry.edit_reason == "Adjusted per timesheet review."
