import pytest
from sqlalchemy.exc import IntegrityError

from app.models.department_manager import DepartmentManager
from app.models.user import User
from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.integration


def test_user_email_is_globally_unique(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    make_user(db_session, organization=org_a, email="duplicate@example.com")

    duplicate = User(
        organization_id=org_b.id,
        email="duplicate@example.com",
        password_hash="irrelevant",
        role="admin",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_employee_role_requires_employee_id(db_session):
    org = make_organization(db_session)

    user = User(
        organization_id=org.id,
        employee_id=None,
        email="employee-role@example.com",
        password_hash="irrelevant",
        role="employee",
    )
    db_session.add(user)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_composite_fk_rejects_employee_from_other_organization(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    employee_in_org_a = make_employee(db_session, organization=org_a)

    # employee_id references an employee whose real organization is org_a,
    # but this row claims org_b — the composite FK on
    # (employee_id, organization_id) must reject this combination even
    # though employee_in_org_a.id genuinely exists.
    user = User(
        organization_id=org_b.id,
        employee_id=employee_in_org_a.id,
        email="cross-tenant@example.com",
        password_hash="irrelevant",
        role="employee",
    )
    db_session.add(user)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_department_managers_composite_fk_rejects_manager_from_other_organization(
    db_session,
):
    """Round B fix: department_managers.user_id used to be a plain FK to
    users.id with nothing tying the row's organization_id to the
    manager's own — a bad insert could assign a manager from org_a to a
    department in org_b. Now a composite FK on (user_id,
    organization_id) -> users(id, organization_id) rejects that
    combination at the database level, even though user_in_org_a.id
    genuinely exists.
    """
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    manager_in_org_a = make_user(db_session, organization=org_a, role="manager")
    department_in_org_b = make_department(db_session, organization=org_b)

    db_session.add(
        DepartmentManager(
            user_id=manager_in_org_a.id,
            department_id=department_in_org_b.id,
            organization_id=org_b.id,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_department_managers_row_cascades_on_user_delete(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    user = make_user(db_session, organization=org, role="manager")

    db_session.add(
        DepartmentManager(
            user_id=user.id, department_id=department.id, organization_id=org.id
        )
    )
    db_session.flush()

    db_session.delete(user)
    db_session.flush()

    remaining = (
        db_session.query(DepartmentManager)
        .filter(DepartmentManager.user_id == user.id)
        .all()
    )
    assert remaining == []
