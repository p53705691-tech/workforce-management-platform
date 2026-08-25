"""DB-level constraint coverage for the ``departments`` table."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.department import Department
from tests.factories import make_department, make_organization

pytestmark = pytest.mark.integration


def test_department_code_is_unique_per_organization(db_session):
    org = make_organization(db_session)
    make_department(db_session, organization=org, code="OPS")

    duplicate = Department(organization_id=org.id, name="Operations Two", code="OPS")
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_department_name_is_unique_per_organization_case_insensitively(db_session):
    org = make_organization(db_session)
    make_department(db_session, organization=org, name="Operations", code="OPS1")

    duplicate = Department(organization_id=org.id, name="OPERATIONS", code="OPS2")
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
