"""DB-level constraint coverage for ``employee_pay_rates``.

Mirrors tests/integration/test_overtime_constraints.py's approach:
exercise constraints directly against the model (bypassing the service
layer) to confirm the database itself protects these invariants. The
exclusion constraint is the single most important test here — it is the
actual "no two overlapping rate periods for the same employee" guarantee
(confirmed rule for this milestone).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.employee_pay_rate import EmployeePayRate
from tests.factories import make_employee, make_organization, make_pay_rate

pytestmark = pytest.mark.integration


def _rate_kwargs(employee, **overrides):
    defaults = {
        "employee_id": employee.id,
        "organization_id": employee.organization_id,
        "hourly_rate": Decimal("20.0000"),
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
    }
    defaults.update(overrides)
    return defaults


def test_exclusion_constraint_rejects_an_overlapping_rate_for_the_same_employee(
    db_session,
):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    make_pay_rate(
        db_session,
        organization=org,
        employee=employee,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )

    overlapping = EmployeePayRate(
        **_rate_kwargs(
            employee, effective_from=date(2021, 1, 1), effective_to=date(2021, 12, 31)
        )
    )
    db_session.add(overlapping)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_non_overlapping_rates_for_the_same_employee_are_allowed(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    make_pay_rate(
        db_session,
        organization=org,
        employee=employee,
        effective_from=date(2020, 1, 1),
        effective_to=date(2020, 12, 31),
    )

    later = EmployeePayRate(
        **_rate_kwargs(employee, effective_from=date(2021, 1, 1), effective_to=None)
    )
    db_session.add(later)

    db_session.flush()  # must not raise


def test_overlapping_rates_for_different_employees_are_allowed(db_session):
    org = make_organization(db_session)
    employee_a = make_employee(db_session, organization=org)
    employee_b = make_employee(db_session, organization=org)
    make_pay_rate(
        db_session,
        organization=org,
        employee=employee_a,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )

    same_range_other_employee = EmployeePayRate(
        **_rate_kwargs(employee_b, effective_from=date(2020, 1, 1), effective_to=None)
    )
    db_session.add(same_range_other_employee)

    db_session.flush()  # must not raise: different employees don't compete


def test_effective_to_before_effective_from_is_rejected(db_session):
    employee = make_employee(db_session)

    rate = EmployeePayRate(
        **_rate_kwargs(
            employee, effective_from=date(2021, 1, 1), effective_to=date(2020, 1, 1)
        )
    )
    db_session.add(rate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_hourly_rate_must_be_positive(db_session):
    employee = make_employee(db_session)

    rate = EmployeePayRate(**_rate_kwargs(employee, hourly_rate=Decimal("0")))
    db_session.add(rate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_negative_hourly_rate_is_rejected(db_session):
    employee = make_employee(db_session)

    rate = EmployeePayRate(**_rate_kwargs(employee, hourly_rate=Decimal("-5.00")))
    db_session.add(rate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_composite_fk_rejects_cross_org_employee_pairing(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    employee_in_org_b = make_employee(db_session, organization=org_b)

    # employee_in_org_b.id genuinely exists, but the rate claims org_a —
    # the composite FK on (employee_id, organization_id) must reject the
    # mismatched combination.
    rate = EmployeePayRate(
        employee_id=employee_in_org_b.id,
        organization_id=org_a.id,
        hourly_rate=Decimal("20.0000"),
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    db_session.add(rate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
