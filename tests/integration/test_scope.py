import pytest

from app.auth.scope import build_scope_for_user
from app.models.department_manager import DepartmentManager
from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.integration


def test_admin_scope_has_no_department_restriction(db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin")

    scope = build_scope_for_user(admin)

    assert scope.role == "admin"
    assert scope.organization_id == org.id
    assert scope.department_ids == frozenset()


def test_manager_scope_contains_only_managed_departments(db_session):
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager")

    db_session.add(
        DepartmentManager(
            user_id=manager.id, department_id=managed.id, organization_id=org.id
        )
    )
    db_session.flush()

    scope = build_scope_for_user(manager)

    assert scope.role == "manager"
    assert scope.department_ids == frozenset({managed.id})
    assert unmanaged.id not in scope.department_ids


def test_employee_scope_is_identified_by_employee_id_not_departments(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = make_user(
        db_session, organization=org, role="employee", employee_id=employee.id
    )

    scope = build_scope_for_user(user)

    assert scope.role == "employee"
    assert scope.employee_id == employee.id
    assert scope.department_ids == frozenset()
