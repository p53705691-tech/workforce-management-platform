"""Round C testing gap: a manager who manages zero departments
(``department_ids=frozenset()``) must degrade safely to an empty result
everywhere department-scoped data is shown -- never silently fall back to
showing the whole organization's data. This locks in current-correct
behavior (``app.auth.scope.build_scope_for_user`` naturally produces an
empty ``department_ids`` for a manager with no ``department_managers``
rows, and every scoped query already treats that the same as "no
departments visible") against a future regression, not fixing a bug.
"""

import pytest

from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def test_manager_with_no_departments_sees_an_empty_dashboard(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    # Deliberately no DepartmentManager row for this manager at all.
    _login(client, manager)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert employee.first_name.encode() not in response.data
    assert department.name.encode() not in response.data


def test_manager_with_no_departments_sees_an_empty_department_list(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.get("/departments")

    assert response.status_code == 200
    assert department.code.encode() not in response.data
    assert b"No departments yet." in response.data


def test_manager_with_no_departments_sees_an_empty_employee_list(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.get("/employees")

    assert response.status_code == 200
    assert employee.employee_number.encode() not in response.data
