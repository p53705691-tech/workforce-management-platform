"""Integration tests for app.services.departments — DB + authorization."""

import pytest
from werkzeug.exceptions import Forbidden, NotFound

from app.auth.scope import AccessScope
from app.services import departments as department_service
from app.services.errors import ValidationError
from tests.factories import make_department, make_organization, make_user

pytestmark = pytest.mark.integration


def _scope(role, organization_id, department_ids=frozenset(), employee_id=None, user_id=1):
    return AccessScope(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


def test_admin_lists_every_department_in_their_organization(db_session):
    org = make_organization(db_session)
    dept_a = make_department(db_session, organization=org)
    dept_b = make_department(db_session, organization=org)
    other_org = make_organization(db_session)
    make_department(db_session, organization=other_org)

    result = department_service.list_departments(_scope("admin", org.id))

    assert {d.id for d in result} == {dept_a.id, dept_b.id}


def test_manager_lists_only_their_managed_departments(db_session):
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    make_department(db_session, organization=org)

    scope = _scope("manager", org.id, department_ids=frozenset({managed.id}))
    result = department_service.list_departments(scope)

    assert [d.id for d in result] == [managed.id]


def test_create_department_requires_admin_role(db_session):
    org = make_organization(db_session)

    with pytest.raises(Forbidden):
        department_service.create_department(
            _scope("manager", org.id), name="Ops", code="OPS"
        )


def test_admin_creates_department_scoped_to_their_own_organization(db_session):
    org = make_organization(db_session)
    # A real user is required here (not the synthetic user_id=1 default):
    # create_department now writes an audit_logs row whose actor_user_id
    # has a real FK to users.id.
    admin = make_user(db_session, organization=org, role="admin")

    department = department_service.create_department(
        _scope("admin", org.id, user_id=admin.id), name="Ops", code="OPS"
    )

    assert department.organization_id == org.id


def test_update_department_rejects_an_unknown_field(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)

    with pytest.raises(ValidationError):
        department_service.update_department(
            _scope("admin", org.id), department.id, organization_id=999
        )


def test_update_department_applies_allowed_fields(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    # A real user is required here (not the synthetic user_id=1 default):
    # update_department now writes an audit_logs row whose actor_user_id
    # has a real FK to users.id.
    admin = make_user(db_session, organization=org, role="admin")

    updated = department_service.update_department(
        _scope("admin", org.id, user_id=admin.id), department.id, name="Renamed"
    )

    assert updated.name == "Renamed"


def test_update_department_requires_admin_role(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    scope = _scope("manager", org.id, department_ids=frozenset({department.id}))

    with pytest.raises(Forbidden):
        department_service.update_department(scope, department.id, name="Renamed")


def test_admin_cannot_update_a_department_in_another_organization(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    department = make_department(db_session, organization=org_b)

    with pytest.raises(NotFound):
        department_service.update_department(
            _scope("admin", org_a.id), department.id, name="Hijacked"
        )


def test_deactivate_department_sets_is_active_false(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    # A real user is required here (not the synthetic user_id=1 default):
    # deactivate_department now writes an audit_logs row whose
    # actor_user_id has a real FK to users.id (see
    # app.services.employees's terminate_employee test for the identical
    # note).
    admin = make_user(db_session, organization=org, role="admin")

    deactivated = department_service.deactivate_department(
        _scope("admin", org.id, user_id=admin.id), department.id
    )

    assert deactivated.is_active is False


def test_deactivate_department_requires_admin_role(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    scope = _scope("manager", org.id, department_ids=frozenset({department.id}))

    with pytest.raises(Forbidden):
        department_service.deactivate_department(scope, department.id)


def test_admin_cannot_deactivate_a_department_in_another_organization(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    department = make_department(db_session, organization=org_b)

    with pytest.raises(NotFound):
        department_service.deactivate_department(_scope("admin", org_a.id), department.id)
