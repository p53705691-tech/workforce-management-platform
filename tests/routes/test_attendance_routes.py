"""Route-level coverage for attendance endpoints.

Mirrors the authorization-focused style of test_schedule_routes.py.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.attendance_entry import AttendanceEntry
from app.models.department_manager import DepartmentManager
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
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


def test_clocking_in_twice_returns_a_clean_error_not_a_500(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    first_response = client.post("/attendance/clock-in", follow_redirects=True)
    assert first_response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 1

    second_response = client.post("/attendance/clock-in", follow_redirects=True)

    assert second_response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 1


def test_employee_cannot_clock_in_on_behalf_of_another_employee(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    # The self-service ClockInForm has no employee_id field at all, but
    # the route must not trust a client-forged one even if it's posted
    # directly (server remains authoritative, never a hidden UI concern).
    response = client.post(
        "/attendance/clock-in",
        data={"employee_id": str(other_employee.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200  # form has no such field, ignored
    assert db_session.query(AttendanceEntry).filter_by(employee_id=other_employee.id).count() == 0


def test_manager_can_clock_in_an_employee_in_a_managed_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/attendance/clock-in",
        data={"employee_id": str(employee.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 1


def test_manager_cannot_clock_in_an_employee_outside_their_managed_department(client, db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=other_dept)
    manager = _make_manager(db_session, org, managed_dept)
    _login(client, manager)

    response = client.post(
        "/attendance/clock-in",
        data={"employee_id": str(employee.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db_session.query(AttendanceEntry).filter_by(employee_id=employee.id).count() == 0


def test_employee_can_clock_out_their_own_open_entry(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        # Recent, not the factory's fixed 2024-01-01 default: clock_out
        # closes with real "now", and a fixed, long-past started_at would
        # otherwise violate Round B's duration_max_24_hours CHECK once
        # far enough from that date.
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        ended_at=None,
        status="open",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/attendance/{entry.id}/clock-out", follow_redirects=True)

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.status == "closed"


def test_employee_cannot_clock_out_another_employees_entry(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=other_employee,
        created_by=admin,
        ended_at=None,
        status="open",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(f"/attendance/{entry.id}/clock-out")

    assert response.status_code == 404
    db_session.refresh(entry)
    assert entry.status == "open"


def test_employee_role_cannot_correct_an_attendance_entry(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"edit_reason": "Trying to change my own record"},
    )

    assert response.status_code == 403


def test_correct_entry_without_a_reason_is_rejected_at_the_route_level(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    _login(client, admin)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"break_minutes": "15"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.edited_by_user_id is None
    assert entry.edited_at is None
    assert entry.break_minutes == 0


def test_correct_entry_break_minutes_overflowing_the_column_is_a_form_error_not_a_500(
    client, db_session
):
    """Security-review finding: a break_minutes large enough to overflow
    the DB's SmallInteger column used to reach correct_entry and raise
    an unhandled DataError. NumberRange's new max on the form field
    catches it before that.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    _login(client, admin)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"break_minutes": "40000", "edit_reason": "Testing an out-of-range value."},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.edited_by_user_id is None


def test_admin_can_correct_an_attendance_entry_with_a_reason(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )
    _login(client, admin)

    response = client.post(
        f"/attendance/{entry.id}/correct",
        data={"break_minutes": "15", "edit_reason": "Adjusted per timesheet review."},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.break_minutes == 15
    assert entry.edited_by_user_id == admin.id
    assert entry.edit_reason == "Adjusted per timesheet review."


def test_employees_own_needs_review_entry_shows_no_clock_out_button(client, db_session):
    """A needs_review entry can never be closed by a plain clock-out
    (attendance_service.clock_out rejects it) — the list page must never
    offer a button that always fails. Regression test for a dead-end
    control found while building the Attendance page's status card.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin,
        started_at=datetime.now(timezone.utc) - timedelta(hours=20),
        ended_at=None, status="needs_review",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/attendance")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Attendance Needs Review" in body
    assert f"/attendance/{entry.id}/clock-out" not in body


def test_manager_attendance_page_has_no_self_service_clock_controls(client, db_session):
    """Clock In/Clock Out are employee self-service (they always act on
    the caller's own record — see ClockInForm/ClockOutForm) and belong on
    the Employee Dashboard only. The admin/manager Attendance page is a
    team management/oversight surface: it must never render a "Clock In"
    action (previously offered "as myself or any employee") or a per-row
    "Clock Out" shortcut for another employee's open entry — a manager
    closes out a missed punch via "Correct" instead, which requires a
    reason and leaves an edit trail.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    manager = _make_manager(db_session, org, department)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=manager,
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ended_at=None, status="open",
    )
    _login(client, manager)

    response = client.get("/attendance")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Clock In" not in body
    assert "Clock in" not in body
    assert "Clock Out" not in body
    assert "Clock out" not in body
    assert f'action="/attendance/{entry.id}/clock-out"' not in body
    assert 'action="/attendance/clock-in"' not in body
    assert "Correct" in body


def test_needs_review_entry_older_than_a_day_still_shows_attention_state(client, db_session):
    """Regression test for the current-status lookup's old fixed 1-day
    lookback: a needs_review entry more than a day old must still surface
    as "Attendance Needs Review", never fall through to "Not Clocked In"
    (which would offer a Clock In button that always fails against the
    DB's open-entry unique index).
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin,
        started_at=datetime.now(timezone.utc) - timedelta(days=5),
        ended_at=None, status="needs_review",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/attendance")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Attendance Needs Review" in body
    assert "Not Clocked In" not in body
    assert f"/attendance/{entry.id}/clock-out" not in body


def test_employee_attendance_page_is_history_only_no_duplicate_primary_action(
    client, db_session
):
    """MVP-1_version2.md §15 reframes Time & Attendance as a pure
    history view for an employee (Date/Scheduled/Worked/Status) — the
    one primary check-in/out action lives on Home only
    (my_attendance.html), so this page must never render a second Clock
    Out control for the same open entry.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin,
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ended_at=None, status="open",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/attendance")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Time & Attendance" in body
    assert f'action="/attendance/{entry.id}/clock-out"' not in body


def test_employee_attendance_page_still_flags_needs_review(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin,
        started_at=datetime.now(timezone.utc) - timedelta(hours=20),
        ended_at=None, business_date=datetime.now(timezone.utc).date(), status="needs_review",
    )
    user = _make_employee_user(db_session, org, employee)
    _login(client, user)

    response = client.get("/attendance")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Attendance Needs Review" in body


def test_manager_filtering_by_an_unmanaged_employee_sees_no_data(client, db_session):
    """A manager passing another department's employee id via
    ?employee_id= must get an empty intersection, never that employee's
    attendance — the department scoping in attendance.list_entries is
    applied before the employee_id equality filter, not after.
    """
    org = make_organization(db_session)
    managed = make_department(db_session, organization=org)
    unmanaged = make_department(db_session, organization=org)
    unmanaged_employee = make_employee(db_session, organization=org, department=unmanaged)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_attendance_entry(
        db_session, organization=org, employee=unmanaged_employee, created_by=admin,
    )
    manager = _make_manager(db_session, org, managed)
    _login(client, manager)

    response = client.get(f"/attendance?employee_id={unmanaged_employee.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No results for this employee" in body


def test_admin_can_filter_attendance_list_by_employee(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee_a = make_employee(db_session, organization=org, department=department)
    employee_b = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    make_attendance_entry(db_session, organization=org, employee=employee_a, created_by=admin)
    make_attendance_entry(db_session, organization=org, employee=employee_b, created_by=admin)
    _login(client, admin)

    response = client.get(f"/attendance?employee_id={employee_a.id}")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'value="{employee_a.id}" selected' in body


def test_clamp_range_bounds_an_excessively_wide_range():
    """Security-review finding: an arbitrary, user-editable ?start=/&end=
    used to be passed straight into attendance_entries_with_context with
    no upper bound, instantiating a CorrectEntryForm per returned row —
    same class of issue app.routes.dashboard's _clamp_range already
    guards against for the report views.
    """
    from datetime import date

    from app.routes.attendance import _MAX_LIST_RANGE_DAYS, _clamp_range

    start, end = _clamp_range(date(1900, 1, 1), date(2100, 1, 1))

    assert (end - start).days == _MAX_LIST_RANGE_DAYS
    assert end == date(2100, 1, 1)


def test_attendance_list_returns_200_for_an_excessively_wide_date_range(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/attendance?start=1900-01-01&end=2100-01-01")

    assert response.status_code == 200
