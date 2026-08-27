"""Route-level coverage for leave endpoints.

Mirrors the authorization-focused style of test_attendance_routes.py.
"""

from datetime import datetime, timedelta, timezone

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


def test_manager_filtering_by_an_unmanaged_employee_sees_no_data(client, db_session):
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org)
    unmanaged_employee = make_employee(db_session, organization=org, department=unmanaged)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_leave_request(db_session, organization=org, employee=unmanaged_employee, requested_by=admin)
    manager = _make_manager(db_session, org, managed)
    _login(client, manager)

    response = client.get(f"/leave?employee_id={unmanaged_employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No results for this filter" in body


def test_admin_can_filter_leave_requests_by_employee(client, db_session):
    org = make_organization(db_session)
    employee_a = make_employee(db_session, organization=org)
    employee_b = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_leave_request(db_session, organization=org, employee=employee_a, requested_by=admin)
    make_leave_request(db_session, organization=org, employee=employee_b, requested_by=admin)
    _login(client, admin)

    response = client.get(f"/leave?employee_id={employee_a.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'value="{employee_a.id}" selected' in body


def test_admin_leave_page_has_no_self_service_request_form(client, db_session):
    """Submitting a leave request "as myself" (or as an arbitrary employee
    picked from a dropdown defaulting to "Myself") is employee
    self-service — see app.forms.LeaveRequestForm vs. AdminLeaveRequestForm
    — and belongs on the employee's own Leave page (my_leave.html) only.
    The admin/manager Leave page is a review/approval surface: it must
    never render a "Request leave" submission form or a "Myself" option.
    """
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/leave")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Request leave" not in body
    assert "Request Leave" not in body
    assert "Myself" not in body
    assert 'action="/leave"' not in body


def test_manager_leave_page_offers_a_single_review_action_for_pending_requests(
    client, db_session
):
    """A pending request must offer one "Review" entry point, not two
    large Approve/Reject controls competing in the same row — Approve and
    Reject are mutually exclusive outcomes of the same decision (see the
    Leave page UX brief). The underlying approve/reject routes and their
    validation rules (decision_note optional vs. required) are unchanged;
    only how the row presents them changed.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    leave_type = make_leave_type(db_session, organization=org)
    manager = _make_manager(db_session, org, department)
    make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type,
        requested_by=manager,
    )
    _login(client, manager)

    response = client.get("/leave")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ">Review<" in body
    assert 'action="/leave/' in body and "/approve" in body
    assert 'action="/leave/' in body and "/reject" in body
    assert "leave-row-pending" in body


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


def test_employee_sees_the_dedicated_my_leave_page(client, db_session):
    """Employee gets a personal Pending/Approved summary
    (MVP-1_version2.md §17), not the admin/manager approval table — and
    never a fabricated "Available" balance, since no accrual ledger
    exists in this system.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/leave")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Pending" in body
    assert "Approved" in body
    assert "Available" not in body


def test_employee_leave_page_tags_a_currently_active_approved_request(client, db_session):
    """"Happening now" / "Upcoming" is display-only sugar derived from an
    approved request's own dates against today (see app.routes.leave —
    mirrors reports.who_is_on_leave_today's same-comparison elsewhere),
    not a new leave rule. A pending request must never get a timing tag:
    it isn't leave yet, only a request for some.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    now = datetime.now(timezone.utc)
    make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type,
        requested_by=admin, status="approved",
        decided_by_user_id=admin.id, decided_at=now,
        starts_at=now - timedelta(hours=2), ends_at=now + timedelta(hours=2),
    )
    make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type,
        requested_by=admin,
        starts_at=now + timedelta(days=30), ends_at=now + timedelta(days=31),
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/leave")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Happening now" in body
    assert "Upcoming" not in body


def test_admin_still_sees_the_management_leave_page(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/leave")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Employee" in body
