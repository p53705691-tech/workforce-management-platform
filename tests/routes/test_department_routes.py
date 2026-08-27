"""Route-level coverage for department management endpoints."""

import pytest

from app.models.department import Department
from app.models.department_manager import DepartmentManager
from tests.factories import (
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

    # Field names are row-prefixed, matching what the real edit form on
    # the departments list page actually renders (one edit form per row,
    # each with a distinct WTForms prefix to avoid id collisions) — see
    # test_admin_edit_department_form_actually_submits_with_csrf_enabled
    # for why this distinction matters.
    response = client.post(
        f"/departments/{department.id}",
        data={f"edit-{department.id}-name": "New Name", f"edit-{department.id}-code": "NEW"},
    )

    assert response.status_code == 302
    db_session.refresh(department)
    assert department.name == "New Name"
    assert department.code == "NEW"


def test_admin_edit_department_form_actually_submits_with_csrf_enabled(
    client, db_session, app
):
    """Regression test: the Edit-department row form renders both its
    csrf_token and its name/code fields differently than a naive
    unprefixed DepartmentForm() would — CSRF is deliberately unprefixed
    (matching the app's global CSRFProtect, which always looks for a
    literal "csrf_token" field) while name/code stay row-prefixed (to
    avoid id collisions between rows). Every other test in this file
    runs with CSRF disabled and posts synthetic unprefixed field names,
    so none of them would have caught a real mismatch between what the
    template renders and what the route validates against.
    """
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org, name="Old Name", code="OLD")
    _login(client, admin)

    app.config["WTF_CSRF_ENABLED"] = True
    try:
        page = client.get("/departments")
        csrf = page.data.decode().split('name="csrf_token" value="')[1].split('"')[0]

        response = client.post(
            f"/departments/{department.id}",
            data={
                f"edit-{department.id}-name": "New Name",
                f"edit-{department.id}-code": "NEW",
                "csrf_token": csrf,
            },
        )
    finally:
        app.config["WTF_CSRF_ENABLED"] = False

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
        data={f"edit-{department.id}-name": "New Name", f"edit-{department.id}-code": "NEW"},
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
            f"edit-{department.id}-name": "New Name",
            f"edit-{department.id}-code": "NEW",
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
        data={
            f"edit-{foreign_department.id}-name": "Hijacked",
            f"edit-{foreign_department.id}-code": foreign_department.code,
        },
    )

    assert response.status_code == 404


def test_admin_can_delete_an_empty_department(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org)
    _login(client, admin)

    response = client.post(f"/departments/{department.id}/delete")

    assert response.status_code == 302
    assert db_session.get(Department, department.id) is None


def test_admin_deleting_a_department_also_removes_its_manager_assignments(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    db_session.add(
        DepartmentManager(
            user_id=manager.id, department_id=department.id, organization_id=org.id
        )
    )
    db_session.flush()
    _login(client, admin)

    response = client.post(f"/departments/{department.id}/delete")

    assert response.status_code == 302
    assert db_session.get(Department, department.id) is None
    assert (
        db_session.query(DepartmentManager)
        .filter_by(department_id=department.id)
        .count()
        == 0
    )


def test_admin_cannot_delete_a_department_with_employees(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org)
    make_employee(db_session, organization=org, department=department)
    _login(client, admin)

    response = client.post(f"/departments/{department.id}/delete", follow_redirects=True)

    assert response.status_code == 200
    assert b"still assigned to this department" in response.data
    assert db_session.get(Department, department.id) is not None


def test_admin_cannot_delete_a_department_with_shifts(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    department = make_department(db_session, organization=org)
    make_shift(db_session, organization=org, department=department, created_by=admin)
    _login(client, admin)

    response = client.post(f"/departments/{department.id}/delete", follow_redirects=True)

    assert response.status_code == 200
    assert b"still reference this department" in response.data
    assert db_session.get(Department, department.id) is not None


def test_manager_cannot_delete_a_department(client, db_session):
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

    response = client.post(f"/departments/{department.id}/delete")

    assert response.status_code == 403
    assert db_session.get(Department, department.id) is not None


def test_admin_cannot_delete_a_department_in_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    foreign_department = make_department(db_session, organization=other_org)
    _login(client, admin)

    response = client.post(f"/departments/{foreign_department.id}/delete")

    assert response.status_code == 404
    assert db_session.get(Department, foreign_department.id) is not None
