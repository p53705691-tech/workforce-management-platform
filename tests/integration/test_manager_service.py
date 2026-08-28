"""app.services.managers — manager account creation and department
assignment (the one account-provisioning workflow this codebase left
unaddressed until this pass — see that module's docstring).
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import verify_password
from app.auth.scope import AccessScope
from app.services.errors import ValidationError
from app.services.managers import (
    assign_department,
    create_manager_account,
    list_managers,
    managed_department_ids,
    unassign_department,
)
from tests.factories import make_department, make_organization, make_user

pytestmark = pytest.mark.integration


def _admin_scope(user):
    return AccessScope(
        user_id=user.id,
        organization_id=user.organization_id,
        role="admin",
        department_ids=frozenset(),
        employee_id=None,
    )


class TestCreateManagerAccount:
    def test_creates_a_manager_role_login_with_no_employee_link(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)

        manager = create_manager_account(scope, "new.manager@example.test", "a-secure-password-1")

        assert manager.role == "manager"
        assert manager.employee_id is None
        assert verify_password(manager.password_hash, "a-secure-password-1")

    def test_rejects_a_duplicate_email(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        create_manager_account(scope, "dup@example.test", "a-secure-password-1")

        with pytest.raises(ValidationError):
            create_manager_account(scope, "dup@example.test", "another-password-2")

    def test_new_manager_starts_with_no_departments(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)

        manager = create_manager_account(scope, "fresh@example.test", "a-secure-password-1")

        assert managed_department_ids(scope, manager.id) == set()


class TestAssignDepartment:
    def test_assigns_and_lists(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        department = make_department(db_session, organization=org)
        manager = create_manager_account(scope, "assign@example.test", "a-secure-password-1")

        assign_department(scope, manager.id, department.id)

        assert managed_department_ids(scope, manager.id) == {department.id}

    def test_assigning_the_same_department_twice_is_a_no_op(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        department = make_department(db_session, organization=org)
        manager = create_manager_account(scope, "twice@example.test", "a-secure-password-1")

        assign_department(scope, manager.id, department.id)
        assign_department(scope, manager.id, department.id)

        assert managed_department_ids(scope, manager.id) == {department.id}

    def test_rejects_a_cross_organization_department(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        manager = create_manager_account(scope, "cross@example.test", "a-secure-password-1")

        other_org = make_organization(db_session)
        foreign_department = make_department(db_session, organization=other_org)

        with pytest.raises(Exception):
            assign_department(scope, manager.id, foreign_department.id)

    def test_unassign_removes_it(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        department = make_department(db_session, organization=org)
        manager = create_manager_account(scope, "remove@example.test", "a-secure-password-1")
        assign_department(scope, manager.id, department.id)

        unassign_department(scope, manager.id, department.id)

        assert managed_department_ids(scope, manager.id) == set()

    def test_unassigning_a_non_existent_assignment_does_not_raise(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        department = make_department(db_session, organization=org)
        manager = create_manager_account(scope, "noop@example.test", "a-secure-password-1")

        unassign_department(scope, manager.id, department.id)  # should not raise


class TestAuthorization:
    def test_manager_cannot_create_a_manager_account(self, db_session):
        org = make_organization(db_session)
        manager_user = make_user(db_session, organization=org, role="manager")
        scope = AccessScope(
            user_id=manager_user.id,
            organization_id=org.id,
            role="manager",
            department_ids=frozenset(),
            employee_id=None,
        )

        with pytest.raises(Exception):
            create_manager_account(scope, "nope@example.test", "a-secure-password-1")

    def test_list_managers_only_returns_managers(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _admin_scope(admin)
        create_manager_account(scope, "one@example.test", "a-secure-password-1")
        make_user(db_session, organization=org, role="admin", email="other-admin@example.test")

        managers = list_managers(scope)

        assert {m.email for m in managers} == {"one@example.test"}
