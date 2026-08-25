"""M9 IDOR sweep: regression coverage for cross-organization and
cross-department access on every ``<int:...>``-keyed route not already
covered by an existing route test file.

Every route exercised here already goes through
``app.auth.scope.get_scoped_or_404`` or an equivalent explicit
organization/department-scoped lookup (see the M9 report). These tests
exist to prove that in practice, not just by reading the code: a
cross-organization or cross-department request must get a plain 404,
never a 403 (which would leak that the row exists) and never a 500.
"""

import pytest

from app.models.department_manager import DepartmentManager
from tests.factories import (
    make_attendance_entry,
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


# -- employees: pay-rate routes (admin-only, but still org-scoped) ----------


def test_pay_rate_routes_404_for_an_employee_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    foreign_employee = make_employee(db_session, organization=other_org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    get_response = client.get(f"/employees/{foreign_employee.id}/pay-rate")
    post_response = client.post(
        f"/employees/{foreign_employee.id}/pay-rate",
        data={"hourly_rate": "25.0000", "effective_from": "2026-01-01"},
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404


# -- labor cost: admin-only per-employee detail (still org-scoped) ----------


def test_labor_cost_employee_detail_404s_for_an_employee_in_another_organization(
    client, db_session
):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    foreign_employee = make_employee(db_session, organization=other_org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get(f"/labor-cost/employees/{foreign_employee.id}")

    assert response.status_code == 404


# -- schedule: update and cancel (publish/assign already covered) ----------


def test_update_shift_404s_for_a_manager_outside_the_shifts_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    shift = make_shift(db_session, organization=org, department=other_dept, created_by=admin)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    # department_id is set to a department the manager *does* manage
    # (a valid SelectField choice) so the request reaches
    # app.services.scheduling._get_shift_for_write's own org/department-
    # scoped lookup on the target shift itself, rather than being
    # rejected earlier by the form's choice list (see
    # test_schedule_routes.py's identical note on this exact ordering).
    response = client.post(
        f"/schedule/{shift.id}",
        data={
            "department_id": managed_dept.id,
            "starts_at": "2026-09-01T09:00",
            "ends_at": "2026-09-01T17:00",
            "break_minutes": "0",
        },
    )

    assert response.status_code == 404


def test_cancel_shift_404s_for_a_shift_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    other_admin = make_user(db_session, organization=other_org, role="admin", password=PASSWORD)
    other_department = make_department(db_session, organization=other_org)
    foreign_shift = make_shift(
        db_session, organization=other_org, department=other_department, created_by=other_admin
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(f"/schedule/{foreign_shift.id}/cancel")

    assert response.status_code == 404


# -- attendance: correct (clock-out is already covered) --------------------


def test_correct_entry_404s_for_an_entry_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    other_employee = make_employee(db_session, organization=other_org)
    other_admin = make_user(db_session, organization=other_org, role="admin", password=PASSWORD)
    foreign_entry = make_attendance_entry(
        db_session, organization=other_org, employee=other_employee, created_by=other_admin
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/attendance/{foreign_entry.id}/correct",
        data={"edit_reason": "Attempted cross-tenant correction."},
    )

    assert response.status_code == 404


def test_correct_entry_404s_for_a_manager_outside_the_employees_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=other_employee, created_by=admin
    )
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"edit_reason": "Attempted cross-department correction."},
    )

    assert response.status_code == 404


# -- leave: approve/reject (cancel is already covered) ----------------------


def test_approve_leave_404s_for_a_request_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    other_employee = make_employee(db_session, organization=other_org)
    other_leave_type = make_leave_type(db_session, organization=other_org)
    other_admin = make_user(db_session, organization=other_org, role="admin", password=PASSWORD)
    foreign_request = make_leave_request(
        db_session,
        organization=other_org,
        employee=other_employee,
        leave_type=other_leave_type,
        requested_by=other_admin,
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(f"/leave/{foreign_request.id}/approve")

    assert response.status_code == 404


def test_reject_leave_404s_for_a_manager_outside_the_employees_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=other_dept)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    leave_request = make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type, requested_by=admin
    )
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        f"/leave/{leave_request.id}/reject", data={"decision_note": "Denied."}
    )

    assert response.status_code == 404
