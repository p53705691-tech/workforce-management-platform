"""DB-level constraint coverage for the ``employees`` table.

These exercise constraints directly against the model (bypassing the
service layer) to confirm the database itself — not just application
code — protects these invariants.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.employee import Employee
from tests.factories import make_department, make_employee, make_organization

pytestmark = pytest.mark.integration


def test_employee_number_is_unique_per_organization(db_session):
    org = make_organization(db_session)
    make_employee(db_session, organization=org, employee_number="EMP-DUP")
    department = make_department(db_session, organization=org)

    duplicate = Employee(
        organization_id=org.id,
        department_id=department.id,
        employee_number="EMP-DUP",
        first_name="Jane",
        last_name="Doe",
        employment_status="active",
        hired_on="2024-01-01",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_department_id_must_belong_to_the_same_organization(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    department_in_org_b = make_department(db_session, organization=org_b)

    # department_in_org_b.id genuinely exists, but the employee claims
    # org_a — the composite FK on (department_id, organization_id) must
    # reject the mismatched combination.
    employee = Employee(
        organization_id=org_a.id,
        department_id=department_in_org_b.id,
        employee_number="EMP-X",
        first_name="Jane",
        last_name="Doe",
        employment_status="active",
        hired_on="2024-01-01",
    )
    db_session.add(employee)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_terminated_on_without_terminated_status_is_rejected(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)

    employee = Employee(
        organization_id=org.id,
        department_id=department.id,
        employee_number="EMP-Y",
        first_name="Jane",
        last_name="Doe",
        employment_status="active",
        hired_on="2024-01-01",
        terminated_on="2024-06-01",
    )
    db_session.add(employee)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_terminated_status_without_terminated_on_is_rejected(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)

    employee = Employee(
        organization_id=org.id,
        department_id=department.id,
        employee_number="EMP-Z",
        first_name="Jane",
        last_name="Doe",
        employment_status="terminated",
        hired_on="2024-01-01",
    )
    db_session.add(employee)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_email_is_unique_per_organization_when_present(db_session):
    org = make_organization(db_session)
    make_employee(db_session, organization=org, email="dup@example.com")
    department = make_department(db_session, organization=org)

    duplicate = Employee(
        organization_id=org.id,
        department_id=department.id,
        employee_number="EMP-EMAIL",
        first_name="Jane",
        last_name="Doe",
        employment_status="active",
        hired_on="2024-01-01",
        email="dup@example.com",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_multiple_employees_with_no_email_are_allowed(db_session):
    org = make_organization(db_session)
    make_employee(db_session, organization=org, email=None)
    make_employee(db_session, organization=org, email=None)

    db_session.flush()  # must not raise
