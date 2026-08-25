"""Route-level coverage for the admin-only, org-scoped audit log view.

The route never queries an unbounded table (it always applies a date
range plus a hard page size — see ``app.routes.audit``), and it is
reachable by admin only, scoped to the admin's own organization.
"""

import pytest

from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def test_anonymous_request_redirects_to_login(client):
    response = client.get("/audit-log")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_manager_cannot_view_the_audit_log(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.get("/audit-log")

    assert response.status_code == 403


def test_employee_cannot_view_the_audit_log(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = make_user(
        db_session, organization=org, role="employee", password=PASSWORD, employee_id=employee.id
    )
    _login(client, user)

    response = client.get("/audit-log")

    assert response.status_code == 403


def test_admin_can_view_the_audit_log(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/audit-log")

    assert response.status_code == 200
    # The login that just happened is itself an audited event.
    assert b"login_success" in response.data


def test_admin_cannot_see_another_organizations_audit_events(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    other_admin = make_user(
        db_session, organization=other_org, role="admin", password=PASSWORD
    )

    # A failed login for the *other* organization's admin creates a
    # login_failed row scoped to other_org — it must never appear in
    # org's own admin's view.
    client.post("/login", data={"email": other_admin.email, "password": "wrong"})

    _login(client, admin)
    response = client.get("/audit-log")

    assert response.status_code == 200
    assert b"login_success" in response.data
    assert b"login_failed" not in response.data
