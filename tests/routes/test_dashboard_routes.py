"""Route-level coverage for the dashboard and reports endpoints.

The core authorization boundary under test (confirmed rule A4, mirrored
from ``tests/routes/test_labor_cost_routes.py``): a manager may see
department labor-cost *totals* and per-employee *overtime hours*, but
never an individual pay rate or a per-employee cost breakdown, anywhere
on the dashboard or the overtime report.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.auth.scope import AccessScope
from app.models.department_manager import DepartmentManager
from app.services.scheduling import business_date_for, organization_timezone
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
    make_overtime_policy,
    make_overtime_tier,
    make_pay_rate,
    make_shift,
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


def _today_for(org):
    scope = AccessScope(
        user_id=1, organization_id=org.id, role="admin", department_ids=frozenset(), employee_id=None
    )
    tz = organization_timezone(scope)
    return business_date_for(datetime.now(timezone.utc), tz)


def _default_policy(session, org):
    policy = make_overtime_policy(
        session, organization=org,
        daily_threshold_hours=Decimal("8.00"), weekly_threshold_hours=Decimal("40.00"),
        week_start_day=0, effective_from=date(2020, 1, 1), effective_to=None,
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


def _published_shift(db_session, org, department, employee, created_by, business_date):
    starts_at = datetime.combine(business_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
    ends_at = starts_at + timedelta(hours=8)
    return make_shift(
        db_session, organization=org, department=department, employee=employee,
        created_by=created_by, starts_at=starts_at, ends_at=ends_at, business_date=business_date,
        status="published", published_at=datetime.now(timezone.utc),
    )


def test_admin_dashboard_shows_org_wide_data(client, db_session):
    org = make_organization(db_session)
    dept_a = make_department(db_session, organization=org)
    dept_b = make_department(db_session, organization=org)
    employee_a = make_employee(
        db_session, organization=org, department=dept_a, first_name="Alice", last_name="Anderson"
    )
    employee_b = make_employee(
        db_session, organization=org, department=dept_b, first_name="Bob", last_name="Brown"
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    today = _today_for(org)
    _published_shift(db_session, org, dept_a, employee_a, admin, today)
    _published_shift(db_session, org, dept_b, employee_b, admin, today)
    _login(client, admin)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Alice Anderson" in response.data
    assert b"Bob Brown" in response.data


def test_manager_dashboard_is_scoped_to_their_own_departments(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    managed_employee = make_employee(
        db_session, organization=org, department=managed_dept,
        first_name="Managed", last_name="Employee",
    )
    other_employee = make_employee(
        db_session, organization=org, department=other_dept,
        first_name="Other", last_name="Employee",
    )
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    today = _today_for(org)
    _published_shift(db_session, org, managed_dept, managed_employee, admin, today)
    _published_shift(db_session, org, other_dept, other_employee, admin, today)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Managed Employee" in response.data
    assert b"Other Employee" not in response.data
    assert other_dept.name.encode() not in response.data


def test_employee_dashboard_shows_only_their_own_data(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own_employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    today = _today_for(org)

    own_shift = _published_shift(db_session, org, department, own_employee, admin, today)
    other_shift = make_shift(
        db_session, organization=org, department=department, employee=other_employee,
        created_by=admin,
        starts_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=14),
        ends_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=20),
        business_date=today, status="published", published_at=datetime.now(timezone.utc),
    )

    user = _make_employee_user(db_session, org, own_employee)
    _login(client, user)

    response = client.get("/dashboard")

    assert response.status_code == 200
    body = response.data.decode()
    # The dashboard renders shift times via the ``local_dt`` filter, which
    # explicitly converts to the organization's own timezone (UTC for this
    # factory-default org) rather than whatever timezone the database
    # session happens to attach on read-back — see app/__init__.py's
    # ``local_dt`` filter docstring for why that distinction matters.
    org_tz = organization_timezone(
        AccessScope(
            user_id=1,
            organization_id=org.id,
            role="employee",
            department_ids=frozenset(),
            employee_id=own_employee.id,
        )
    )
    assert own_shift.starts_at.astimezone(org_tz).strftime("%H:%M") in body
    assert other_shift.starts_at.astimezone(org_tz).strftime("%H:%M") not in body


def test_manager_never_sees_pay_rate_or_per_employee_cost_on_dashboard(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee_one = make_employee(db_session, organization=org, department=department)
    employee_two = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _default_policy(db_session, org)
    make_pay_rate(
        db_session, organization=org, employee=employee_one,
        hourly_rate=Decimal("20.0000"), effective_from=date(2020, 1, 1),
    )
    make_pay_rate(
        db_session, organization=org, employee=employee_two,
        hourly_rate=Decimal("30.0000"), effective_from=date(2020, 1, 1),
    )
    today = _today_for(org)
    for employee in (employee_one, employee_two):
        started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=started_at, ended_at=started_at + timedelta(hours=8),
            business_date=today, status="closed",
        )
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.get("/dashboard")
    body = response.data.decode()

    assert response.status_code == 200
    # Department total: 8h * $20 + 8h * $30 = 400.00.
    assert "400.00" in body
    # Per-employee totals must never appear.
    assert "160.00" not in body
    assert "240.00" not in body
    # Neither must an hourly rate.
    assert "20.0000" not in body
    assert "30.0000" not in body


def test_manager_never_sees_pay_rate_or_cost_on_overtime_report(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    ot_employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _default_policy(db_session, org)
    make_pay_rate(
        db_session, organization=org, employee=ot_employee,
        hourly_rate=Decimal("50.0000"), effective_from=date(2020, 1, 1),
    )
    today = _today_for(org)
    started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
    # 10 worked hours: 8 regular + 2 hours of daily overtime.
    make_attendance_entry(
        db_session, organization=org, employee=ot_employee, created_by=admin,
        started_at=started_at, ended_at=started_at + timedelta(hours=10),
        business_date=today, status="closed",
    )
    manager = _make_manager(db_session, org, department)
    _login(client, manager)

    response = client.get(
        f"/reports/overtime?department_id={department.id}&start={today.isoformat()}&end={today.isoformat()}"
    )
    body = response.data.decode()

    assert response.status_code == 200
    # The overtime hours figure is allowed to appear...
    assert "2.00" in body
    # ...but no rate or cost figure ever may.
    assert "50.0000" not in body
    assert "400.00" not in body  # regular-hours cost (8h * $50)
    assert "150.00" not in body  # OT cost (2h * 1.5 * $50)
    assert "550.00" not in body  # combined per-employee total


def test_dashboard_returns_200_with_no_pay_rate_or_policy_configured(client, db_session):
    """Round C testing gap: the dashboard's department cost totals go
    through the same isolating app.services.labor_cost.department_cost_summary
    as tests/routes/test_labor_cost_routes.py's equivalent test -- an
    employee with worked hours but no configured pay rate/overtime
    policy must not turn the dashboard into a 500.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    today = _today_for(org)
    started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
    make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin,
        started_at=started_at, ended_at=started_at + timedelta(hours=8),
        business_date=today, status="closed",
    )
    _login(client, admin)

    response = client.get("/dashboard")

    assert response.status_code == 200


def test_overtime_report_returns_200_with_no_pay_rate_or_policy_configured(
    client, db_session
):
    """Same gap as above, for /reports/overtime:
    app.services.reports.overtime_summary already isolates a per-employee
    configuration gap (see its docstring) rather than failing the whole
    report, returning that employee with ``configured=False`` instead.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    today = _today_for(org)
    started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
    make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin,
        started_at=started_at, ended_at=started_at + timedelta(hours=8),
        business_date=today, status="closed",
    )
    _login(client, admin)

    response = client.get(
        f"/reports/overtime?department_id={department.id}&start={today.isoformat()}&end={today.isoformat()}"
    )

    assert response.status_code == 200
    assert b"Not available (no pay rate or overtime policy configured)" in response.data


def test_manager_cannot_reach_a_department_they_do_not_manage(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.get(f"/reports/overtime?department_id={other_dept.id}")

    assert response.status_code == 404


def test_employee_role_cannot_reach_reports(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    assert client.get("/reports/overtime").status_code == 403
    assert client.get("/reports/hours-trend").status_code == 403
