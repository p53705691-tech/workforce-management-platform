"""Coverage for the Phase 2 application shell's nav-visibility guards.

These don't re-test authorization — the route-level `@role_required`
tests already own that (see test_department_routes.py,
test_employee_routes.py, test_audit_log_routes.py, etc.). This module
only pins down the claim the shell makes on top of that: a signed-in
user is never shown a sidebar link to a page their role can't reach, and
the shell chrome doesn't render at all for an unauthenticated request.
"""

import pytest

from tests.factories import make_employee, make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def test_login_page_renders_no_shell_chrome(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert b'id="primary-sidebar"' not in response.data
    assert b'class="shell"' not in response.data


def test_admin_sees_every_nav_group(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b'id="primary-sidebar"' in response.data
    for label in (b"Employees", b"Departments", b"Overtime Report", b"Hours Trend", b"Labor Cost", b"Audit Log"):
        assert label in response.data


def test_manager_sees_people_and_insight_but_not_admin(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.get("/dashboard")

    assert response.status_code == 200
    for label in (b"Employees", b"Departments", b"Overtime Report", b"Hours Trend", b"Labor Cost"):
        assert label in response.data
    assert b"Audit Log" not in response.data


def test_employee_sees_only_operations_and_dashboard(client, db_session):
    org = make_organization(db_session)
    employee_record = make_employee(db_session, organization=org)
    employee = make_user(
        db_session,
        organization=org,
        role="employee",
        password=PASSWORD,
        employee_id=employee_record.id,
    )
    _login(client, employee)

    response = client.get("/dashboard")

    assert response.status_code == 200
    for label in (b"Schedule", b"Attendance", b"Leave", b"Dashboard"):
        assert label in response.data
    for label in (b"Employees", b"Departments", b"Overtime Report", b"Hours Trend", b"Labor Cost", b"Audit Log"):
        assert label not in response.data


def test_active_nav_link_carries_aria_current(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/audit-log")

    assert response.status_code == 200
    assert b'aria-current="page"' in response.data


def test_employee_detail_page_keeps_employees_nav_active(client, db_session):
    # Admin, not manager: get_employee's scoping restricts a manager to
    # their *managed* departments (see app/services/employees.py), which
    # this test has no need to set up — admin bypasses that scoping.
    org = make_organization(db_session)
    employee_record = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get(f"/employees/{employee_record.id}")

    assert response.status_code == 200
    assert b'aria-current="page"' in response.data
