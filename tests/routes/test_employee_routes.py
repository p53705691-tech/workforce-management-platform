"""Route-level coverage for employee management endpoints.

Includes the core IDOR test for this milestone (a manager must get a
plain 404, not a 403 or a silently-scoped result, when reading or
editing another department's employee) and the mass-assignment test
(submitting a privileged field must have zero effect).
"""

import pytest

from datetime import datetime, timezone

from flask import g

from app.auth.scope import AccessScope
from app.models.department_manager import DepartmentManager
from app.models.employee import Employee
from app.services import employees as employee_service
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
    make_shift,
    make_user,
)

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def _forget_cached_current_user():
    """Drop Flask-Login's per-``g`` ``current_user`` cache.

    See the identical helper in ``tests.routes.test_auth_routes`` for why
    this is needed: the ``app`` fixture keeps one app context pushed for
    the whole test session, so ``g._login_user`` would otherwise survive
    across multiple requests within a single test, masking an account
    state change made in between.
    """
    g.pop("_login_user", None)


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
        db_session,
        organization=org,
        role="employee",
        password=PASSWORD,
        employee_id=employee.id,
    )


def test_employee_role_cannot_list_all_employees(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/employees")

    assert response.status_code == 403


def test_manager_cannot_read_employee_in_another_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.get(f"/employees/{other_employee.id}")

    assert response.status_code == 404


def test_manager_cannot_edit_employee_in_another_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        f"/employees/{other_employee.id}",
        data={
            "department_id": other_dept.id,
            "employee_number": other_employee.employee_number,
            "first_name": "Hacked",
            "last_name": other_employee.last_name,
            "employment_status": "active",
        },
    )

    assert response.status_code == 404
    db_session.refresh(other_employee)
    assert other_employee.first_name != "Hacked"


def test_manager_can_read_and_edit_employee_in_managed_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    get_response = client.get(f"/employees/{employee.id}")
    assert get_response.status_code == 200

    post_response = client.post(
        f"/employees/{employee.id}",
        data={
            "department_id": managed_dept.id,
            "employee_number": employee.employee_number,
            "first_name": "Updated",
            "last_name": employee.last_name,
            "employment_status": "active",
        },
    )

    assert post_response.status_code == 302
    db_session.refresh(employee)
    assert employee.first_name == "Updated"


def test_employee_can_read_their_own_record(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own_employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, own_employee)
    _login(client, user)

    response = client.get(f"/employees/{own_employee.id}")

    assert response.status_code == 200


def test_employee_cannot_read_another_employees_record(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own_employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, own_employee)
    _login(client, user)

    response = client.get(f"/employees/{other_employee.id}")

    assert response.status_code == 404


def test_admin_can_manage_employees_across_departments_within_org(client, db_session):
    org = make_organization(db_session)
    dept_a = make_department(db_session, organization=org)
    dept_b = make_department(db_session, organization=org)
    employee_a = make_employee(db_session, organization=org, department=dept_a)
    employee_b = make_employee(db_session, organization=org, department=dept_b)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    for employee in (employee_a, employee_b):
        response = client.get(f"/employees/{employee.id}")
        assert response.status_code == 200


def test_admin_cannot_act_on_employee_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    foreign_employee = make_employee(db_session, organization=other_org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    get_response = client.get(f"/employees/{foreign_employee.id}")
    assert get_response.status_code == 404

    post_response = client.post(
        f"/employees/{foreign_employee.id}",
        data={
            "department_id": foreign_employee.department_id,
            "employee_number": foreign_employee.employee_number,
            "first_name": "Hacked",
            "last_name": foreign_employee.last_name,
            "employment_status": "active",
        },
    )
    assert post_response.status_code == 404

    terminate_response = client.post(
        f"/employees/{foreign_employee.id}/terminate",
        data={"terminated_on": "2024-06-01"},
    )
    assert terminate_response.status_code == 404

    create_account_response = client.post(
        f"/employees/{foreign_employee.id}/create-account",
        data={"email": "hacked@example.com", "password": "correct horse battery staple"},
    )
    assert create_account_response.status_code == 404

    reset_password_response = client.post(
        f"/employees/{foreign_employee.id}/reset-password",
        data={
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )
    assert reset_password_response.status_code == 404


def test_create_employee_mass_assignment_of_organization_id_has_no_effect(
    client, db_session
):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/employees",
        data={
            "department_id": department.id,
            "employee_number": "EMP-NEW",
            "first_name": "New",
            "last_name": "Hire",
            "employment_status": "active",
            "hired_on": "2024-01-01",
            "organization_id": other_org.id,
        },
    )

    assert response.status_code == 302
    employee = db_session.query(Employee).filter_by(employee_number="EMP-NEW").one()
    assert employee.organization_id == org.id


def test_update_employee_mass_assignment_of_organization_id_has_no_effect(
    client, db_session
):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}",
        data={
            "department_id": department.id,
            "employee_number": employee.employee_number,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "employment_status": "active",
            "organization_id": other_org.id,
        },
    )

    assert response.status_code == 302
    db_session.refresh(employee)
    assert employee.organization_id == org.id


def test_admin_can_terminate_employee(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/terminate", data={"terminated_on": "2024-06-01"}
    )

    assert response.status_code == 302
    db_session.refresh(employee)
    assert employee.employment_status == "terminated"
    assert str(employee.terminated_on) == "2024-06-01"


def test_terminating_an_employee_signs_out_their_active_session_immediately(
    client, db_session
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    login = make_user(
        db_session,
        organization=org,
        role="employee",
        employee_id=employee.id,
        password=PASSWORD,
    )
    admin = make_user(db_session, organization=org, role="admin")

    _login(client, login)
    assert client.get("/dashboard").status_code == 200
    _forget_cached_current_user()

    # Terminated via the service directly (same DB the running app/client
    # share) rather than a second HTTP login as admin, which would
    # overwrite this test client's single session cookie.
    employee_service.terminate_employee(
        AccessScope(
            user_id=admin.id,
            organization_id=org.id,
            role="admin",
            department_ids=frozenset(),
            employee_id=None,
        ),
        employee.id,
        "2024-06-01",
    )
    db_session.flush()
    _forget_cached_current_user()

    # The employee's own session cookie is unchanged, but load_user now
    # rejects it on the very next request (see app.models.user.load_user
    # and terminate_employee's new is_active=False) rather than only at
    # their next login.
    still_working_response = client.get("/dashboard")
    assert still_working_response.status_code == 302
    assert "/login" in still_working_response.headers["Location"]


def test_manager_cannot_terminate_employee(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.post(
        f"/employees/{employee.id}/terminate", data={"terminated_on": "2024-06-01"}
    )

    assert response.status_code == 403


def test_manager_filtering_by_an_unmanaged_department_sees_no_data(client, db_session):
    """A manager passing another department's id via ?department_id=
    must get an empty list, never that department's employees —
    _filtered_employees filters over employee_service.list_employees's
    already manager-scoped result, so the department_id equality filter
    can only narrow further, never widen past that scope.
    """
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org)
    make_employee(db_session, organization=org, department=unmanaged)
    manager = _make_manager(db_session, org, managed)
    _login(client, manager)

    response = client.get(f"/employees?department_id={unmanaged.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No employees match this search" in body


def test_admin_can_filter_employee_list_by_department_and_status(client, db_session):
    org = make_organization(db_session)
    department_a = make_department(db_session, organization=org)
    department_b = make_department(db_session, organization=org)
    make_employee(
        db_session, organization=org, department=department_a, employment_status="active"
    )
    make_employee(
        db_session, organization=org, department=department_b, employment_status="active"
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get(f"/employees?department_id={department_a.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'value="{department_a.id}" selected' in body


def test_admin_can_search_employees_by_name(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    match = make_employee(
        db_session, organization=org, department=department,
        first_name="Jordan", last_name="Lee",
    )
    other = make_employee(
        db_session, organization=org, department=department,
        first_name="Sam", last_name="Rivera",
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/employees?q=jordan")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Jordan" in body
    assert "Sam Rivera" not in body


def test_admin_can_search_employees_by_employee_number_or_email(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    by_number = make_employee(
        db_session, organization=org, department=department, employee_number="EMP-4242",
    )
    by_email = make_employee(
        db_session, organization=org, department=department, email="rivera@example.com",
    )
    make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response_number = client.get("/employees?q=4242")
    body_number = response_number.get_data(as_text=True)
    assert by_number.employee_number in body_number

    response_email = client.get("/employees?q=rivera@example.com")
    body_email = response_email.get_data(as_text=True)
    assert by_email.employee_number in body_email


def test_manager_search_is_scoped_to_their_managed_departments(client, db_session):
    """A manager searching by name must never see a match from an
    unmanaged department — search filters over an already-scoped list,
    never widens it.
    """
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org)
    make_employee(
        db_session, organization=org, department=managed,
        first_name="Alex", last_name="Kim",
    )
    make_employee(
        db_session, organization=org, department=unmanaged,
        first_name="Alexis", last_name="Nguyen",
    )
    manager = _make_manager(db_session, org, managed)
    _login(client, manager)

    response = client.get("/employees?q=alex")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Alex Kim" in body
    assert "Alexis Nguyen" not in body


def test_search_with_no_matches_shows_the_no_results_state(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/employees?q=nobody-with-this-name")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No employees match this search" in body


def test_employee_detail_shows_linked_account_role(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _make_employee_user(db_session, org, employee)
    _login(client, admin)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Employee" in body
    assert "No login account" not in body


def test_employee_detail_shows_no_login_account_when_none_linked(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No login account" in body


def test_employee_detail_shows_upcoming_shifts_and_recent_attendance_for_manager(
    client, db_session
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    make_shift(
        db_session, organization=org, department=department, employee=employee,
        created_by=manager, status="published", published_at=datetime.now(timezone.utc),
    )
    make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=manager,
    )
    _login(client, manager)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Upcoming Shifts" in body
    assert "Recent Attendance" in body


def test_employee_viewing_own_detail_page_does_not_see_schedule_attendance_sections(
    client, db_session
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Upcoming Shifts" not in body
    assert "Recent Attendance" not in body


def test_employee_detail_shows_create_account_form_when_no_account_linked(
    client, db_session
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Create login account" in body


def test_employee_detail_hides_create_account_form_when_account_already_linked(
    client, db_session
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _make_employee_user(db_session, org, employee)
    _login(client, admin)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Create login account" not in body


def test_manager_never_sees_create_account_form(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.get(f"/employees/{employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Create login account" not in body


def test_admin_can_create_a_login_account_for_an_employee_with_none(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/create-account",
        data={"email": "new.hire@example.com", "password": "correct horse battery staple"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    from app.models.user import User

    created = db_session.query(User).filter_by(employee_id=employee.id).one()
    assert created.email == "new.hire@example.com"
    assert created.role == "employee"
    assert created.is_active is True
    assert created.password_hash != "correct horse battery staple"


def test_creating_a_second_account_for_the_same_employee_is_rejected(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _make_employee_user(db_session, org, employee)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/create-account",
        data={"email": "duplicate@example.com", "password": "correct horse battery staple"},
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "already has a login account" in body


def test_duplicate_email_is_rejected_with_a_friendly_message(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(
        db_session, organization=org, role="admin", password=PASSWORD, email="taken@example.com"
    )
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/create-account",
        data={"email": "taken@example.com", "password": "correct horse battery staple"},
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "already in use" in body


def test_manager_cannot_create_a_login_account(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.post(
        f"/employees/{employee.id}/create-account",
        data={"email": "new.hire@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 403


def test_short_password_is_rejected_at_the_form_level(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/create-account",
        data={"email": "new.hire@example.com", "password": "short"},
        follow_redirects=True,
    )

    from app.models.user import User

    assert response.status_code == 200
    assert db_session.query(User).filter_by(employee_id=employee.id).first() is None


def test_admin_can_reset_an_existing_accounts_password(client, db_session):
    from app.auth.passwords import verify_password

    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    account = _make_employee_user(db_session, org, employee)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/reset-password",
        data={
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Password reset" in body
    db_session.refresh(account)
    assert verify_password(account.password_hash, "a-brand-new-password")


def test_admin_reset_password_signs_out_the_employees_existing_session(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    account = _make_employee_user(db_session, org, employee)

    employee_client = client.application.test_client()
    employee_client.post("/login", data={"email": account.email, "password": PASSWORD})
    _forget_cached_current_user()
    assert employee_client.get("/dashboard").status_code == 200
    _forget_cached_current_user()

    _login(client, admin)
    client.post(
        f"/employees/{employee.id}/reset-password",
        data={
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )
    _forget_cached_current_user()

    response = employee_client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_reset_password_clears_lockout(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    account = _make_employee_user(db_session, org, employee)
    account.failed_login_count = 5
    from datetime import datetime, timedelta, timezone
    account.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    db_session.flush()
    _login(client, admin)

    client.post(
        f"/employees/{employee.id}/reset-password",
        data={
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )

    db_session.refresh(account)
    assert account.failed_login_count == 0
    assert account.locked_until is None


def test_cannot_reset_password_for_an_employee_with_no_account(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/reset-password",
        data={
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "no login account" in body


def test_manager_cannot_reset_a_password(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    _make_employee_user(db_session, org, employee)
    _login(client, manager)

    response = client.post(
        f"/employees/{employee.id}/reset-password",
        data={
            "new_password": "a-brand-new-password",
            "confirm_new_password": "a-brand-new-password",
        },
    )

    assert response.status_code == 403


def test_employee_detail_shows_reset_password_only_when_account_exists(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    with_account = make_employee(db_session, organization=org, department=department)
    without_account = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _make_employee_user(db_session, org, with_account)
    _login(client, admin)

    body_with = client.get(f"/employees/{with_account.id}").get_data(as_text=True)
    body_without = client.get(f"/employees/{without_account.id}").get_data(as_text=True)

    assert "Reset password" in body_with
    assert "Reset password" not in body_without


def test_employee_can_view_their_own_profile(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(
        db_session, organization=org, department=department, phone="555-0100"
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/employees/profile")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "My Profile" in body
    assert "555-0100" in body
    assert user.email in body


def test_employee_can_update_their_own_phone_number(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(
        "/employees/profile", data={"phone": "555-0199"}, follow_redirects=True
    )

    assert response.status_code == 200
    db_session.refresh(employee)
    assert employee.phone == "555-0199"


def test_employee_cannot_change_company_controlled_fields_via_profile(client, db_session):
    """The profile form has no field for department/status/name — even
    a hand-crafted extra POST field must have zero effect, since
    update_own_contact_info only ever touches phone.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    other_department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    client.post(
        "/employees/profile",
        data={"phone": "555-0199", "department_id": str(other_department.id)},
        follow_redirects=True,
    )

    db_session.refresh(employee)
    assert employee.department_id == department.id


def test_admin_cannot_reach_the_employee_profile_route(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/employees/profile")

    assert response.status_code == 403


def test_manager_cannot_reach_the_employee_profile_route(client, db_session):
    org = make_organization(db_session)
    manager = _make_manager(db_session, org)
    _login(client, manager)

    response = client.get("/employees/profile")

    assert response.status_code == 403


def test_pay_rate_larger_than_the_column_can_store_is_a_form_error_not_a_500(
    client, db_session
):
    """Security-review finding: an hourly_rate large enough to overflow
    the DB's NUMERIC(10, 4) column used to reach set_pay_rate and raise
    an unhandled DataError. NumberRange's new max on the form field
    catches it before that.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/pay-rate",
        data={"hourly_rate": "99999999", "effective_from": "2026-01-01"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    from app.models.employee_pay_rate import EmployeePayRate

    assert (
        db_session.query(EmployeePayRate).filter_by(employee_id=employee.id).count() == 0
    )
