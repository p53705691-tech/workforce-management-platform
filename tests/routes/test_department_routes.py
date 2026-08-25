"""Route-level coverage for department management endpoints."""

import pytest

from app.models.department import Department
from app.models.department_manager import DepartmentManager
from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def test_admin_can_list_departments(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_department(db_session, organization=org)
    _login(client, admin)

    response = client.get("/departments")

    assert response.status_code == 200


def test_employee_cannot_list_departments(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = make_user(
        db_session,
        organization=org,
        role="employee",
        password=PASSWORD,
        employee_id=employee.id,
    )
    _login(client, user)

    response = client.get("/departments")

    assert response.status_code == 403


def test_manager_lists_only_their_managed_departments(client, db_session):
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org, code="UNM")
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    db_session.add(
        DepartmentManager(
            user_id=manager.id, department_id=managed.id, organization_id=org.id
        )
    )
    db_session.flush()
    _login(client, manager)

    response = client.get("/departments")

    assert response.status_code == 200
    assert managed.code.encode() in response.data
    assert unmanaged.code.encode() not in response.data


def test_admin_creates_department(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post("/departments", data={"name": "Warehouse", "code": "WH1"})

    assert response.status_code == 302
    department = db_session.query(Department).filter_by(code="WH1").one()
    assert department.organization_id == org.id


def test_manager_cannot_create_department(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.post("/departments", data={"name": "Warehouse", "code": "WH1"})

    assert response.status_code == 403


def test_create_department_mass_assignment_of_organization_id_has_no_effect(
    client, db_session
):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/departments",
        data={"name": "Warehouse", "code": "WH1", "organization_id": other_org.id},
    )

    assert response.status_code == 302
    department = db_session.query(Department).filter_by(code="WH1").one()
    assert department.organization_id == org.id


def test_admin_can_deactivate_department(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org)
    _login(client, admin)

    response = client.post(f"/departments/{department.id}/deactivate")

    assert response.status_code == 302
    db_session.refresh(department)
    assert department.is_active is False


def test_manager_cannot_deactivate_department(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    db_session.add(
        DepartmentManager(
            user_id=manager.id, department_id=department.id, organization_id=org.id
        )
    )
    db_session.flush()
    _login(client, manager)

    response = client.post(f"/departments/{department.id}/deactivate")

    assert response.status_code == 403


def test_admin_cannot_deactivate_department_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    foreign_department = make_department(db_session, organization=other_org)
    _login(client, admin)

    response = client.post(f"/departments/{foreign_department.id}/deactivate")

    assert response.status_code == 404


def test_admin_can_update_a_department(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org, name="Old Name", code="OLD")
    _login(client, admin)

    response = client.post(
        f"/departments/{department.id}",
        data={"name": "New Name", "code": "NEW"},
    )

    assert response.status_code == 302
    db_session.refresh(department)
    assert department.name == "New Name"
    assert department.code == "NEW"


def test_manager_cannot_update_a_department(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org, name="Old Name", code="OLD")
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    db_session.add(
        DepartmentManager(
            user_id=manager.id, department_id=department.id, organization_id=org.id
        )
    )
    db_session.flush()
    _login(client, manager)

    response = client.post(
        f"/departments/{department.id}",
        data={"name": "New Name", "code": "NEW"},
    )

    assert response.status_code == 403
    db_session.refresh(department)
    assert department.name == "Old Name"
    assert department.code == "OLD"


def test_update_department_mass_assignment_has_no_effect(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org, name="Old Name", code="OLD")
    _login(client, admin)

    response = client.post(
        f"/departments/{department.id}",
        data={
            "name": "New Name",
            "code": "NEW",
            "organization_id": other_org.id,
            "is_active": "false",
        },
    )

    assert response.status_code == 302
    db_session.refresh(department)
    # The form only ever reads name/code; organization_id/is_active are
    # not fields on DepartmentForm at all, so submitting them has no
    # effect on the row beyond the two legitimate field changes.
    assert department.name == "New Name"
    assert department.code == "NEW"
    assert department.organization_id == org.id
    assert department.is_active is True


def test_admin_cannot_update_a_department_in_another_organization_via_route(
    client, db_session
):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    foreign_department = make_department(db_session, organization=other_org, name="Foreign")
    _login(client, admin)

    response = client.post(
        f"/departments/{foreign_department.id}",
        data={"name": "Hijacked", "code": foreign_department.code},
    )

    assert response.status_code == 404
