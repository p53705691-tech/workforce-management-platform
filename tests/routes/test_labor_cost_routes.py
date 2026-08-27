"""Route-level coverage for labor cost / pay rate endpoints.

The core authorization boundary under test (confirmed rule A4): a
manager may reach department/date-range *totals*, but every route that
would reveal an individual pay rate or a per-employee cost breakdown is
admin-only, enforced at the route layer itself (``role_required``), not
just by what a template happens to render.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.department_manager import DepartmentManager
from app.models.employee_pay_rate import EmployeePayRate
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
    make_overtime_policy,
    make_overtime_tier,
    make_pay_rate,
    make_user,
)

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def _make_manager(db_session, org, *managed_departments):
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    for department in managed_departments:
        db_session.add(
            DepartmentManager(
                user_id=manager.id, department_id=department.id, organization_id=org.id
            )
        )
    db_session.flush()
    return manager


def _make_employee_user(db_session, org, employee):
    return make_user(
        db_session, organization=org, role="employee", password=PASSWORD, employee_id=employee.id
    )


def _default_policy(session, org):
    policy = make_overtime_policy(
        session,
        organization=org,
        daily_threshold_hours=Decimal("8.00"),
        weekly_threshold_hours=Decimal("40.00"),
        week_start_day=0,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    make_overtime_tier(
        session, policy=policy, scope="daily", tier_order=0,
        from_hours=Decimal("0.00"), to_hours=Decimal("2.00"), multiplier=Decimal("1.50"),
    )
    make_overtime_tier(
        session, policy=policy, scope="daily", tier_order=1,
        from_hours=Decimal("2.00"), to_hours=None, multiplier=Decimal("2.00"),
    )
    make_overtime_tier(
        session, policy=policy, scope="weekly", tier_order=0,
        from_hours=Decimal("0.00"), to_hours=None, multiplier=Decimal("1.50"),
    )
    return policy


def test_manager_can_view_department_totals(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    _default_policy(db_session, org)
    make_pay_rate(
        db_session,
        organization=org,
        employee=employee,
        hourly_rate=Decimal("20.0000"),
        effective_from=date(2020, 1, 1),
    )
    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 5),
    )
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.get(
        f"/labor-cost?department_id={department.id}&start=2026-01-05&end=2026-01-05"
    )

    assert response.status_code == 200
    assert b"160.00" in response.data
    # Rule A4: a manager never sees the per-employee breakdown section at
    # all, not just its numbers — the whole drill-down UI is admin-only.
    assert b"Per-Employee Breakdown" not in response.data


def test_admin_sees_per_employee_breakdown_links_for_the_department(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get(
        f"/labor-cost?department_id={department.id}&start=2026-01-05&end=2026-01-05"
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Per-Employee Breakdown" in body
    assert f"/labor-cost/employees/{employee.id}" in body


def test_manager_cannot_reach_admin_only_employee_cost_detail(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.get(f"/labor-cost/employees/{employee.id}")

    assert response.status_code == 403


def test_manager_cannot_view_or_set_a_pay_rate(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    get_response = client.get(f"/employees/{employee.id}/pay-rate")
    post_response = client.post(
        f"/employees/{employee.id}/pay-rate",
        data={
            "hourly_rate": "25.0000",
            "effective_from": "2026-01-01",
        },
    )

    assert get_response.status_code == 403
    assert post_response.status_code == 403
    assert db_session.query(EmployeePayRate).filter_by(employee_id=employee.id).count() == 0


def test_employee_role_cannot_reach_labor_cost_or_pay_rate_routes(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    assert client.get("/labor-cost").status_code == 403
    assert client.get(f"/labor-cost/employees/{employee.id}").status_code == 403
    assert client.get(f"/employees/{employee.id}/pay-rate").status_code == 403
    assert (
        client.post(
            f"/employees/{employee.id}/pay-rate",
            data={"hourly_rate": "25.0000", "effective_from": "2026-01-01"},
        ).status_code
        == 403
    )


def test_admin_can_set_a_pay_rate_via_the_route(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        f"/employees/{employee.id}/pay-rate",
        data={"hourly_rate": "25.5000", "effective_from": "2026-01-01"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    rate = (
        db_session.query(EmployeePayRate).filter_by(employee_id=employee.id).one()
    )
    assert rate.hourly_rate == Decimal("25.5000")


def test_department_totals_return_200_with_no_pay_rate_or_policy_configured(
    client, db_session
):
    """Round C testing gap: an employee who worked hours but has no pay
    rate/overtime policy configured for the range must not turn this
    route into a 500 -- app.services.labor_cost.department_cost_summary
    already isolates the per-employee ValidationError (see
    tests/integration/test_labor_cost_service.py::TestDepartmentCostSummary
    and its
    test_one_unconfigured_employee_does_not_blank_the_rest_of_the_department),
    surfacing it as an explicit count instead. This locks that behavior
    in at the route/template layer too.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    # No overtime policy, no pay rate anywhere in this organization.
    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 5),
    )
    _login(client, admin)

    response = client.get(
        f"/labor-cost?department_id={department.id}&start=2026-01-05&end=2026-01-05"
    )

    assert response.status_code == 200
    assert b"missing rate/policy configuration" in response.data


def test_employee_cost_detail_returns_200_with_no_pay_rate_or_policy_configured(
    client, db_session
):
    """Same gap as above, for the admin-only per-employee breakdown: the
    route already catches range_cost_for_employee's ValidationError and
    flashes it (see app.routes.labor_cost.employee_detail) rather than
    letting it propagate into a 500.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 5),
    )
    _login(client, admin)

    response = client.get(
        f"/labor-cost/employees/{employee.id}?start=2026-01-05&end=2026-01-05"
    )

    assert response.status_code == 200
    assert b"No pay rate configured" in response.data


def test_admin_can_view_the_admin_only_employee_cost_detail(client, db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _default_policy(db_session, org)
    make_pay_rate(
        db_session,
        organization=org,
        employee=employee,
        hourly_rate=Decimal("20.0000"),
        effective_from=date(2020, 1, 1),
    )
    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 5),
    )
    _login(client, admin)

    response = client.get(
        f"/labor-cost/employees/{employee.id}?start=2026-01-05&end=2026-01-05"
    )

    assert response.status_code == 200
    assert b"160.00" in response.data
