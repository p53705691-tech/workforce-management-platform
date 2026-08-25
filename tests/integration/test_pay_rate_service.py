"""Integration tests for app.services.pay_rates — DB + authorization.

Pay rates are admin-only end to end (confirmed rule A4): every function
here rejects a manager, not just an employee.
"""

from datetime import date
from decimal import Decimal

import pytest
from werkzeug.exceptions import Forbidden

from app.auth.scope import AccessScope
from app.services import pay_rates as pay_rate_service
from app.services.errors import ValidationError
from tests.factories import make_employee, make_organization, make_pay_rate, make_user

pytestmark = pytest.mark.integration


def _scope(role, organization_id, department_ids=frozenset(), employee_id=None, user_id=1):
    return AccessScope(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


class TestSetPayRate:
    def test_admin_can_set_a_pay_rate(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, user_id=admin.id)

        pay_rate = pay_rate_service.set_pay_rate(
            scope, employee.id, Decimal("25.5000"), date(2026, 1, 1)
        )

        assert pay_rate.hourly_rate == Decimal("25.5000")
        assert pay_rate.effective_to is None

    def test_manager_cannot_set_a_pay_rate(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        manager = make_user(db_session, organization=org, role="manager")
        scope = _scope("manager", org.id, user_id=manager.id)

        with pytest.raises(Forbidden):
            pay_rate_service.set_pay_rate(
                scope, employee.id, Decimal("25.5000"), date(2026, 1, 1)
            )

    def test_employee_role_cannot_set_a_pay_rate(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        scope = _scope("employee", org.id, employee_id=employee.id)

        with pytest.raises(Forbidden):
            pay_rate_service.set_pay_rate(
                scope, employee.id, Decimal("25.5000"), date(2026, 1, 1)
            )

    def test_zero_or_negative_rate_is_rejected_with_a_validation_error(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, user_id=admin.id)

        with pytest.raises(ValidationError):
            pay_rate_service.set_pay_rate(
                scope, employee.id, Decimal("0"), date(2026, 1, 1)
            )

    def test_effective_to_before_effective_from_is_rejected(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, user_id=admin.id)

        with pytest.raises(ValidationError):
            pay_rate_service.set_pay_rate(
                scope,
                employee.id,
                Decimal("25.0000"),
                date(2026, 1, 1),
                effective_to=date(2025, 1, 1),
            )

    def test_overlapping_rate_is_translated_to_a_validation_error(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, user_id=admin.id)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            effective_from=date(2026, 1, 1),
            effective_to=None,
        )

        with pytest.raises(ValidationError):
            pay_rate_service.set_pay_rate(
                scope, employee.id, Decimal("30.0000"), date(2026, 6, 1)
            )

    def test_cross_org_employee_id_is_rejected_with_a_validation_error(self, db_session):
        org_a = make_organization(db_session)
        org_b = make_organization(db_session)
        employee_in_org_b = make_employee(db_session, organization=org_b)
        admin = make_user(db_session, organization=org_a, role="admin")
        scope = _scope("admin", org_a.id, user_id=admin.id)

        with pytest.raises(ValidationError):
            pay_rate_service.set_pay_rate(
                scope, employee_in_org_b.id, Decimal("25.0000"), date(2026, 1, 1)
            )


class TestResolvePayRate:
    def test_returns_the_rate_in_force_on_the_given_date(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("18.0000"),
            effective_from=date(2020, 1, 1),
            effective_to=date(2020, 12, 31),
        )
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("21.0000"),
            effective_from=date(2021, 1, 1),
            effective_to=None,
        )

        assert pay_rate_service.resolve_pay_rate(
            employee.id, org.id, date(2020, 6, 1)
        ) == Decimal("18.0000")
        assert pay_rate_service.resolve_pay_rate(
            employee.id, org.id, date(2026, 1, 1)
        ) == Decimal("21.0000")

    def test_returns_none_when_no_rate_covers_the_date(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)

        assert pay_rate_service.resolve_pay_rate(employee.id, org.id, date(2026, 1, 1)) is None


class TestListPayRateHistory:
    def test_admin_sees_full_history_most_recent_first(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, user_id=admin.id)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            effective_from=date(2020, 1, 1),
            effective_to=date(2020, 12, 31),
        )
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            effective_from=date(2021, 1, 1),
            effective_to=None,
        )

        history = pay_rate_service.list_pay_rate_history(scope, employee.id)

        assert [rate.effective_from for rate in history] == [date(2021, 1, 1), date(2020, 1, 1)]

    def test_manager_cannot_list_pay_rate_history(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        manager = make_user(db_session, organization=org, role="manager")
        scope = _scope("manager", org.id, user_id=manager.id)

        with pytest.raises(Forbidden):
            pay_rate_service.list_pay_rate_history(scope, employee.id)
