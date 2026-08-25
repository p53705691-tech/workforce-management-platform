"""Integration tests for app.services.employees — DB + authorization."""

import pytest
from werkzeug.exceptions import Forbidden, NotFound

from app.auth.scope import AccessScope
from app.services import employees as employee_service
from app.services.errors import ValidationError
from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.integration


def _scope(role, organization_id, department_ids=frozenset(), employee_id=None, user_id=1):
    return AccessScope(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


def _required_fields(department_id, **overrides):
    fields = {
        "department_id": department_id,
        "employee_number": "E1",
        "first_name": "A",
        "last_name": "B",
        "employment_status": "active",
        "hired_on": "2024-01-01",
    }
    fields.update(overrides)
    return fields


def test_admin_lists_every_employee_in_their_organization(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    emp_a = make_employee(db_session, organization=org, department=department)
    emp_b = make_employee(db_session, organization=org, department=department)
    other_org = make_organization(db_session)
    make_employee(db_session, organization=other_org)

    result = employee_service.list_employees(_scope("admin", org.id))

    assert {e.id for e in result} == {emp_a.id, emp_b.id}


def test_manager_lists_only_employees_in_managed_departments(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    managed_emp = make_employee(db_session, organization=org, department=managed_dept)
    make_employee(db_session, organization=org, department=other_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))
    result = employee_service.list_employees(scope)

    assert [e.id for e in result] == [managed_emp.id]


def test_employee_lists_only_their_own_record(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own = make_employee(db_session, organization=org, department=department)
    make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=own.id)
    result = employee_service.list_employees(scope)

    assert [e.id for e in result] == [own.id]


def test_get_employee_outside_manager_scope_is_not_found(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))

    with pytest.raises(NotFound):
        employee_service.get_employee(scope, other_employee.id)


def test_get_employee_from_another_organization_is_not_found(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    employee_in_b = make_employee(db_session, organization=org_b)

    with pytest.raises(NotFound):
        employee_service.get_employee(_scope("admin", org_a.id), employee_in_b.id)


def test_employee_cannot_get_another_employees_record(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own = make_employee(db_session, organization=org, department=department)
    other = make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=own.id)

    with pytest.raises(NotFound):
        employee_service.get_employee(scope, other.id)


def test_create_employee_requires_admin_role(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    scope = _scope("manager", org.id, department_ids=frozenset({department.id}))

    with pytest.raises(Forbidden):
        employee_service.create_employee(scope, **_required_fields(department.id))


def test_create_employee_rejects_a_department_from_another_organization(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    foreign_department = make_department(db_session, organization=other_org)

    with pytest.raises(ValidationError):
        employee_service.create_employee(
            _scope("admin", org.id), **_required_fields(foreign_department.id)
        )


def test_create_employee_rejects_a_missing_required_field(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    fields = _required_fields(department.id)
    del fields["hired_on"]

    with pytest.raises(ValidationError):
        employee_service.create_employee(_scope("admin", org.id), **fields)


def test_create_employee_rejects_an_unknown_field(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)

    with pytest.raises(ValidationError):
        # organization_id is not part of the create allowlist at all — a
        # caller cannot smuggle a foreign organization in through it.
        employee_service.create_employee(
            _scope("admin", org.id),
            **_required_fields(department.id, organization_id=other_org.id),
        )


def test_admin_creates_employee_scoped_to_their_own_organization(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)

    employee = employee_service.create_employee(
        _scope("admin", org.id), **_required_fields(department.id)
    )

    assert employee.organization_id == org.id


def test_manager_cannot_update_employee_outside_managed_departments(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))

    with pytest.raises(NotFound):
        employee_service.update_employee(scope, other_employee.id, first_name="Changed")


def test_manager_updates_employee_in_a_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    # A real user is required here (not the synthetic user_id=1 default):
    # update_employee now writes an audit_logs row whose actor_user_id has
    # a real FK to users.id (see test_terminate_employee_sets_status_and_date_together's
    # identical note).
    manager = make_user(db_session, organization=org, role="manager")

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )
    updated = employee_service.update_employee(scope, employee.id, first_name="Changed")

    assert updated.first_name == "Changed"


def test_update_employee_rejects_an_unknown_field(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)

    with pytest.raises(ValidationError):
        employee_service.update_employee(
            _scope("admin", org.id), employee.id, organization_id=999
        )


def test_update_employee_rejects_setting_status_to_terminated_directly(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)

    with pytest.raises(ValidationError):
        employee_service.update_employee(
            _scope("admin", org.id), employee.id, employment_status="terminated"
        )


def test_manager_cannot_reassign_employee_to_an_unmanaged_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))

    with pytest.raises(ValidationError):
        employee_service.update_employee(scope, employee.id, department_id=other_dept.id)


def test_terminate_employee_sets_status_and_date_together(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    # A real user is required here (not the synthetic user_id=1 default):
    # terminate_employee now writes an audit_logs row whose actor_user_id
    # has a real FK to users.id.
    admin = make_user(db_session, organization=org, role="admin")

    terminated = employee_service.terminate_employee(
        _scope("admin", org.id, user_id=admin.id), employee.id, "2024-06-01"
    )

    assert terminated.employment_status == "terminated"
    assert str(terminated.terminated_on) == "2024-06-01"


def test_terminate_employee_requires_admin_role(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    scope = _scope("manager", org.id, department_ids=frozenset({department.id}))

    with pytest.raises(Forbidden):
        employee_service.terminate_employee(scope, employee.id, "2024-06-01")
