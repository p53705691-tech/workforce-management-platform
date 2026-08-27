"""Route-level coverage for schedule management endpoints.

Mirrors the authorization-focused style of test_employee_routes.py: a
manager acting outside their managed departments must be rejected, and
an employee-role user must not be able to perform manager/admin actions.
"""

from datetime import date, datetime, timezone

import pytest
from freezegun import freeze_time

from app.auth.scope import AccessScope
from app.models.department_manager import DepartmentManager
from app.models.shift import Shift
from app.routes.schedule import _default_date_range
from app.services.scheduling import business_date_for, organization_timezone
from tests.factories import (
    make_department,
    make_employee,
    make_organization,
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


@freeze_time("2026-01-01 23:30:00")
def test_default_date_range_uses_the_organizations_local_date_not_the_servers(
    db_session,
):
    """Round B fix: this module used to compute its default window from
    date.today() (the server's date) rather than the organization's own
    timezone (rule A1), unlike app.routes.dashboard's already-correct
    pattern. At 23:30 UTC, an org in Pacific/Auckland (UTC+13 in
    January) is already well into the next local day -- the two must not
    silently disagree about what "today" is.
    """
    org = make_organization(db_session, timezone="Pacific/Auckland")
    scope = AccessScope(
        user_id=1,
        organization_id=org.id,
        role="admin",
        department_ids=frozenset(),
        employee_id=None,
    )

    start, _end = _default_date_range(scope)

    expected_local_today = business_date_for(
        datetime.now(timezone.utc), organization_timezone(scope)
    )
    assert start == expected_local_today
    assert start == date(2026, 1, 2)
    assert start != date.today()


def test_employee_role_cannot_create_a_shift(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(
        "/schedule",
        data={
            "department_id": department.id,
            "starts_at": "2026-09-01T09:00",
            "ends_at": "2026-09-01T17:00",
            "break_minutes": "0",
        },
    )

    assert response.status_code == 403


def test_employee_can_view_their_own_schedule(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/schedule")

    assert response.status_code == 200


def test_employee_sees_the_dedicated_my_schedule_page(client, db_session):
    """Employee gets its own composition (MVP-1_version2.md §14), not
    the Admin/Manager Schedule page with a create-shift form/filters.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/schedule")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "My Schedule" in body
    assert "New shift" not in body


def test_admin_still_sees_the_management_schedule_page(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/schedule")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "New shift" in body


def test_manager_cannot_create_a_shift_in_an_unmanaged_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/schedule",
        data={
            "department_id": other_dept.id,
            "starts_at": "2026-09-01T09:00",
            "ends_at": "2026-09-01T17:00",
            "break_minutes": "0",
            "employee_id": "0",
        },
        follow_redirects=True,
    )

    # other_dept isn't among the department choices the route builds for
    # this manager (department_service.list_departments already scopes to
    # managed departments), so WTForms rejects it as "not a valid choice"
    # before the service's own _validate_department_for_write ever runs —
    # belt-and-suspenders authorization, form layer and service layer.
    assert response.status_code == 200
    assert db_session.query(Shift).filter_by(department_id=other_dept.id).count() == 0


def test_manager_can_create_a_shift_in_a_managed_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/schedule",
        data={
            "department_id": managed_dept.id,
            "starts_at": "2026-09-01T09:00",
            "ends_at": "2026-09-01T17:00",
            "break_minutes": "0",
            "employee_id": "0",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(Shift).filter_by(department_id=managed_dept.id).count() == 1


def test_invalid_shift_creation_reopens_the_form_with_errors_and_entered_values(
    client, db_session
):
    """Regression test: an invalid submission used to unconditionally
    redirect back to a fresh GET /schedule — which builds a brand-new,
    error-free ShiftCreateForm, so the "New shift" disclosure never
    auto-opened and every value the user had typed was silently lost,
    with only an easy-to-miss flash message as any indication something
    went wrong. It must now re-render the same page directly, with the
    submitted form's own errors and entered values intact.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/schedule",
        data={
            "department_id": department.id,
            # starts_at deliberately omitted: DataRequired fails validation
            # before the service layer is ever reached.
            "ends_at": "2026-09-01T17:00",
            "break_minutes": "0",
            "employee_id": "0",
            "notes": "Covering for Sam",
        },
    )

    assert response.status_code == 200
    body = response.data.decode()
    assert "This field is required." in body
    assert 'class="create-disclosure" open' in body
    # The rest of what was typed survives the re-render, not just the error.
    assert 'value="Covering for Sam"' in body
    assert db_session.query(Shift).filter_by(department_id=department.id).count() == 0


def test_manager_cannot_assign_an_employee_from_another_organization(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    foreign_employee = make_employee(db_session, organization=other_org)
    manager = _make_manager(db_session, org, department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    shift = make_shift(db_session, organization=org, department=department, created_by=admin)
    _login(client, manager)

    response = client.post(
        f"/schedule/{shift.id}/assign",
        data={"employee_id": foreign_employee.id},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(shift)
    assert shift.employee_id is None


def test_manager_cannot_publish_a_shift_in_an_unmanaged_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=other_dept)
    manager = _make_manager(db_session, org, managed_dept)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    shift = make_shift(
        db_session, organization=org, department=other_dept, employee=employee, created_by=admin
    )
    _login(client, manager)

    response = client.post(f"/schedule/{shift.id}/publish")

    assert response.status_code == 404
    db_session.refresh(shift)
    assert shift.status == "draft"


def test_admin_can_publish_and_cancel_a_shift(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    shift = make_shift(
        db_session, organization=org, department=department, employee=employee, created_by=admin
    )
    _login(client, admin)

    publish_response = client.post(f"/schedule/{shift.id}/publish", follow_redirects=True)
    assert publish_response.status_code == 200
    db_session.refresh(shift)
    assert shift.status == "published"

    cancel_response = client.post(f"/schedule/{shift.id}/cancel", follow_redirects=True)
    assert cancel_response.status_code == 200
    db_session.refresh(shift)
    assert shift.status == "cancelled"


def test_create_shift_mass_assignment_of_organization_id_has_no_effect(client, db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/schedule",
        data={
            "department_id": department.id,
            "starts_at": "2026-09-01T09:00",
            "ends_at": "2026-09-01T17:00",
            "break_minutes": "0",
            "employee_id": "0",
            "organization_id": other_org.id,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    shift = db_session.query(Shift).filter_by(department_id=department.id).one()
    assert shift.organization_id == org.id


def test_manager_filtering_by_an_unmanaged_department_sees_no_data(client, db_session):
    """A manager passing another department's id via ?department_id=
    must get an empty intersection, never that department's shifts — the
    manager's own department scoping in list_shifts is applied before
    the department_id equality filter, not after.
    """
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_shift(db_session, organization=org, department=unmanaged, created_by=admin)
    manager = _make_manager(db_session, org, managed)
    _login(client, manager)

    response = client.get(f"/schedule?department_id={unmanaged.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No results for this department" in body


def test_admin_can_filter_schedule_by_department(client, db_session):
    org = make_organization(db_session)
    department_a = make_department(db_session, organization=org)
    department_b = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_shift(db_session, organization=org, department=department_a, created_by=admin)
    make_shift(db_session, organization=org, department=department_b, created_by=admin)
    _login(client, admin)

    response = client.get(f"/schedule?department_id={department_a.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'value="{department_a.id}" selected' in body


def test_shift_hours_column_reflects_break_minutes(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_shift(
        db_session, organization=org, department=department, created_by=admin,
        starts_at=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2024, 1, 1, 17, 0, tzinfo=timezone.utc),
        break_minutes=30,
    )
    _login(client, admin)

    response = client.get(
        "/schedule?start=2024-01-01&end=2024-01-01"
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "7.50h" in body


def test_clamp_range_bounds_an_excessively_wide_range():
    """Security-review finding: an arbitrary, user-editable ?start=/&end=
    used to be passed straight into list_shifts with no upper bound,
    instantiating a ShiftUpdateForm/AssignEmployeeForm per returned row —
    same class of issue app.routes.dashboard's _clamp_range already
    guards against for the report views.
    """
    from datetime import date

    from app.routes.schedule import _MAX_LIST_RANGE_DAYS, _clamp_range

    start, end = _clamp_range(date(1900, 1, 1), date(2100, 1, 1))

    assert (end - start).days == _MAX_LIST_RANGE_DAYS
    assert end == date(2100, 1, 1)


def test_schedule_list_returns_200_for_an_excessively_wide_date_range(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/schedule?start=1900-01-01&end=2100-01-01")

    assert response.status_code == 200
