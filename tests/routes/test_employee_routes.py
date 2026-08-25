"""Route-level coverage for employee management endpoints.

Includes the core IDOR test for this milestone (a manager must get a
plain 404, not a 403 or a silently-scoped result, when reading or
editing another department's employee) and the mass-assignment test
(submitting a privileged field must have zero effect).
"""

import pytest

from app.models.department_manager import DepartmentManager
from app.models.employee import Employee
from tests.factories import make_department, make_employee, make_organization, make_user

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
