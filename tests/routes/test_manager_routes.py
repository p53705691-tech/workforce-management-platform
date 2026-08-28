"""Manager routes: admin-only manager account creation and department
assignment.
"""

import pytest

from tests.factories import make_department, make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def test_admin_can_view_managers_page(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/managers")

    assert response.status_code == 200
    assert b"Create a manager account" in response.data


def test_manager_cannot_view_managers_page(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.get("/managers")

    assert response.status_code == 403


def test_anonymous_user_cannot_view_managers_page(client):
    response = client.get("/managers")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_can_create_a_manager_account(client, db_session):
    from app.models.user import User

    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/managers",
        data={"email": "new.manager@example.test", "password": "a-secure-password-1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    created = db_session.query(User).filter_by(email="new.manager@example.test").one()
    assert created.role == "manager"


def test_admin_can_assign_and_unassign_a_department(client, db_session):
    from app.models.department_manager import DepartmentManager
    from app.models.user import User

    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org)
    _login(client, admin)
    client.post("/managers", data={"email": "assignee@example.test", "password": "a-secure-password-1"})
    manager = db_session.query(User).filter_by(email="assignee@example.test").one()

    assign_response = client.post(
        f"/managers/{manager.id}/departments",
        data={"department_id": department.id},
        follow_redirects=True,
    )
    assert assign_response.status_code == 200
    assert (
        db_session.query(DepartmentManager)
        .filter_by(user_id=manager.id, department_id=department.id)
        .first()
        is not None
    )

    remove_response = client.post(
        f"/managers/{manager.id}/departments/{department.id}/remove", follow_redirects=True
    )
    assert remove_response.status_code == 200
    assert (
        db_session.query(DepartmentManager)
        .filter_by(user_id=manager.id, department_id=department.id)
        .first()
        is None
    )


def test_manager_cannot_create_a_manager_account(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.post(
        "/managers", data={"email": "nope@example.test", "password": "a-secure-password-1"}
    )

    assert response.status_code == 403


def test_assigning_a_foreign_department_is_rejected(client, db_session):
    from app.models.user import User

    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    other_org = make_organization(db_session)
    foreign_department = make_department(db_session, organization=other_org)
    _login(client, admin)
    client.post("/managers", data={"email": "scoped@example.test", "password": "a-secure-password-1"})
    manager = db_session.query(User).filter_by(email="scoped@example.test").one()

    response = client.post(
        f"/managers/{manager.id}/departments", data={"department_id": foreign_department.id}
    )

    assert response.status_code == 404
