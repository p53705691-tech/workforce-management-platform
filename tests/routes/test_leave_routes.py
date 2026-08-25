"""Route-level coverage for leave endpoints.

Mirrors the authorization-focused style of test_attendance_routes.py.
"""

from datetime import datetime, timezone

import pytest

from app.models.department_manager import DepartmentManager
from app.models.leave_request import LeaveRequest
from tests.factories import (
    make_department,
    make_employee,
    make_leave_request,
    make_leave_type,
    make_organization,
    make_shift,
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


def test_requesting_leave_for_another_employee_as_a_non_manager_is_rejected(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    leave_type = make_leave_type(db_session, organization=org)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    # The self-service LeaveRequestForm has no employee_id field at all,
    # but the route must not trust a client-forged one even if it's
    # posted directly (server remains authoritative).
    response = client.post(
        "/leave",
        data={
            "employee_id": str(other_employee.id),
            "leave_type_id": str(leave_type.id),
            "starts_at": "2026-01-01T09:00",
            "ends_at": "2026-01-01T17:00",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert (
        db_session.query(LeaveRequest).filter_by(employee_id=other_employee.id).count() == 0
    )


def test_employee_can_request_their_own_leave(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    leave_type = make_leave_type(db_session, organization=org)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(
        "/leave",
        data={
            "leave_type_id": str(leave_type.id),
            "starts_at": "2026-01-01T09:00",
            "ends_at": "2026-01-01T17:00",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(LeaveRequest).filter_by(employee_id=employee.id).count() == 1


def test_manager_can_request_leave_for_a_managed_employee(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    leave_type = make_leave_type(db_session, organization=org)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/leave",
        data={
            "employee_id": str(employee.id),
            "leave_type_id": str(leave_type.id),
            "starts_at": "2026-01-01T09:00",
            "ends_at": "2026-01-01T17:00",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(LeaveRequest).filter_by(employee_id=employee.id).count() == 1


def test_admin_can_approve_a_leave_request_without_conflicts(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    leave_request = make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type, requested_by=admin
    )
    _login(client, admin)

    response = client.post(
        f"/leave/{leave_request.id}/approve",
        data={"decision_note": "Approved."},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(leave_request)
    assert leave_request.status == "approved"
    assert leave_request.decided_by_user_id == admin.id
    assert leave_request.decided_at is not None


def test_approving_a_leave_request_with_a_conflicting_shift_does_not_approve_it(
    client, db_session
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        starts_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    _login(client, admin)

    response = client.post(f"/leave/{leave_request.id}/approve", follow_redirects=True)

    assert response.status_code == 200
    db_session.refresh(leave_request)
    assert leave_request.status == "pending"


def test_employee_role_cannot_approve_a_leave_request(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    leave_request = make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type, requested_by=admin
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/leave/{leave_request.id}/approve")

    assert response.status_code == 403


def test_reject_without_a_reason_is_rejected_at_the_route_level(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    leave_request = make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type, requested_by=admin
    )
    _login(client, admin)

    response = client.post(f"/leave/{leave_request.id}/reject", data={}, follow_redirects=True)

    assert response.status_code == 200
    db_session.refresh(leave_request)
    assert leave_request.status == "pending"


def test_employee_can_cancel_their_own_pending_request_via_route(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    leave_request = make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type, requested_by=admin
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/leave/{leave_request.id}/cancel", follow_redirects=True)

    assert response.status_code == 200
    db_session.refresh(leave_request)
    assert leave_request.status == "cancelled"


def test_employee_cannot_cancel_another_employees_request_via_route(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=other_employee,
        leave_type=leave_type,
        requested_by=admin,
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/leave/{leave_request.id}/cancel")

    assert response.status_code == 404
    db_session.refresh(leave_request)
    assert leave_request.status == "pending"
