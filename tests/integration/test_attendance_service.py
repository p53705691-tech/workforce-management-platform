"""Integration tests for app.services.attendance — DB + authorization."""

from datetime import date, datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from werkzeug.exceptions import Forbidden

from app.auth.scope import AccessScope
from app.services import attendance as attendance_service
from app.services.errors import ValidationError
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
    make_shift,
    make_user,
)

pytestmark = pytest.mark.integration


def _scope(role, organization_id, department_ids=frozenset(), employee_id=None, user_id=1):
    return AccessScope(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


@freeze_time("2026-01-01 12:00:00")
def test_clock_in_matches_a_single_published_shift_within_the_grace_window(db_session):
    # Frozen "now": Round B's clock_in backdating window
    # (_validate_started_at_window) would otherwise reject this test's
    # fixed, far-past "at" value once real time moves more than 90 days
    # past 2026-01-01.
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    # clock_in always uses "now" for a self-service employee, so the only
    # way to control the clock-in instant deterministically is a manual
    # (admin) clock-in with an explicit "at" — 45 minutes before the
    # shift starts, still within the 60-minute grace window (rule A3).
    clock_in_time = datetime(2026, 1, 1, 8, 15, tzinfo=timezone.utc)
    admin_scope = _scope("admin", org.id, user_id=admin.id)
    entry = attendance_service.clock_in(
        admin_scope, employee_id=employee.id, at=clock_in_time
    )

    assert entry.shift_id == shift.id


@freeze_time("2026-01-01 12:00:00")
def test_clock_in_leaves_shift_id_null_when_zero_shifts_match(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    # Two hours before the shift starts: outside the 60-minute grace window.
    far_before = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    entry = attendance_service.clock_in(admin_scope, employee_id=employee.id, at=far_before)

    assert entry.shift_id is None


@freeze_time("2026-01-01 12:00:00")
def test_clock_in_leaves_shift_id_null_when_multiple_shifts_match(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    # Two adjacent published shifts whose grace windows both cover the
    # same clock-in instant.
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc),
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 45, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    ambiguous_time = datetime(2026, 1, 1, 9, 40, tzinfo=timezone.utc)
    entry = attendance_service.clock_in(admin_scope, employee_id=employee.id, at=ambiguous_time)

    assert entry.shift_id is None


def test_clock_in_on_behalf_of_someone_else_is_manager_scope_checked(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee_in_other_dept = make_employee(db_session, organization=org, department=other_dept)
    manager = make_user(db_session, organization=org, role="manager")

    manager_scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(ValidationError):
        attendance_service.clock_in(manager_scope, employee_id=employee_in_other_dept.id)


def test_manager_can_clock_in_an_employee_in_a_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    manager = make_user(db_session, organization=org, role="manager")

    manager_scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    entry = attendance_service.clock_in(manager_scope, employee_id=employee.id)

    assert entry.employee_id == employee.id
    assert entry.source == "manual"
    assert entry.status == "open"


def test_employee_cannot_clock_in_on_behalf_of_another_employee(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    other_employee = make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(Forbidden):
        attendance_service.clock_in(scope, employee_id=other_employee.id)


def test_employee_cannot_set_a_custom_clock_in_time(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(ValidationError):
        attendance_service.clock_in(
            scope, at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        )


def test_clock_in_twice_is_rejected_as_a_clean_validation_error(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    attendance_service.clock_in(admin_scope, employee_id=employee.id)

    with pytest.raises(ValidationError):
        attendance_service.clock_in(admin_scope, employee_id=employee.id)


def test_clock_in_rejects_a_started_at_in_the_future(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(ValidationError):
        attendance_service.clock_in(admin_scope, employee_id=employee.id, at=future)


def test_clock_in_rejects_a_started_at_too_far_in_the_past(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    too_old = datetime.now(timezone.utc) - timedelta(days=91)

    with pytest.raises(ValidationError):
        attendance_service.clock_in(admin_scope, employee_id=employee.id, at=too_old)


def test_correct_entry_rejects_a_started_at_in_the_future(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(ValidationError):
        attendance_service.correct_entry(
            scope, entry.id, edit_reason="Adjusted per review.", started_at=future
        )


def test_correct_entry_rejects_a_started_at_too_far_in_the_past(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    too_old = datetime.now(timezone.utc) - timedelta(days=91)

    with pytest.raises(ValidationError):
        attendance_service.correct_entry(
            scope, entry.id, edit_reason="Adjusted per review.", started_at=too_old
        )


def test_self_service_employee_cannot_clock_out_a_needs_review_entry(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime.now(timezone.utc) - timedelta(hours=20),
        ended_at=None,
        status="needs_review",
    )

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(ValidationError):
        attendance_service.clock_out(scope, entry.id)

    db_session.refresh(entry)
    assert entry.status == "needs_review"
    assert entry.ended_at is None


def test_admin_can_still_resolve_a_needs_review_entry_via_correct_entry(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    started_at = datetime.now(timezone.utc) - timedelta(hours=20)
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=started_at,
        ended_at=None,
        status="needs_review",
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    resolved = attendance_service.correct_entry(
        scope,
        entry.id,
        edit_reason="Employee forgot to clock out; confirmed via timesheet.",
        ended_at=started_at + timedelta(hours=8),
    )

    assert resolved.status == "closed"
    assert resolved.ended_at is not None


def test_clock_in_rejects_a_terminated_employee(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(
        db_session,
        organization=org,
        department=department,
        employment_status="terminated",
        terminated_on=date(2026, 1, 1),
    )
    admin = make_user(db_session, organization=org, role="admin")

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    with pytest.raises(ValidationError):
        attendance_service.clock_in(admin_scope, employee_id=employee.id)


def test_terminating_an_employee_does_not_touch_their_existing_attendance_entry(db_session):
    """Fix 1 only blocks a *new* clock-in — an employee's attendance
    history must survive being terminated afterward untouched.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )

    employee.employment_status = "terminated"
    employee.terminated_on = date(2026, 1, 1)
    db_session.flush()

    db_session.refresh(entry)
    assert entry.employee_id == employee.id
    assert entry.status == "closed"


@freeze_time("2024-01-01 10:00:00")
def test_clock_out_closes_an_open_entry(db_session):
    # Frozen "now": clock_out always closes with "now" for a self-service
    # employee, and the entry's fixed started_at default (2024-01-01
    # 09:00) would otherwise be many months before real "now", violating
    # Round B's new duration_max_24_hours CHECK on the resulting entry.
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        ended_at=None,
        status="open",
    )

    scope = _scope("employee", org.id, employee_id=employee.id)
    closed = attendance_service.clock_out(scope, entry.id)

    assert closed.status == "closed"
    assert closed.ended_at is not None


def test_clock_out_rejects_an_already_closed_entry(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(ValidationError):
        attendance_service.clock_out(scope, entry.id)


def test_correct_entry_without_edit_reason_is_rejected_before_touching_the_db(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        attendance_service.correct_entry(scope, entry.id, edit_reason="   ")

    db_session.refresh(entry)
    assert entry.edited_by_user_id is None
    assert entry.edited_at is None


def test_employee_cannot_correct_their_own_attendance_entry(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session, organization=org, employee=employee, created_by=admin
    )

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(Forbidden):
        attendance_service.correct_entry(scope, entry.id, edit_reason="Fixing my own time")


def test_correct_entry_sets_edited_fields_together(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    corrected = attendance_service.correct_entry(
        scope,
        entry.id,
        edit_reason="Employee forgot to clock out on time; adjusted from manager notes.",
        ended_at=datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc),
    )

    assert corrected.ended_at == datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc)
    assert corrected.edited_by_user_id == admin.id
    assert corrected.edited_at is not None
    assert corrected.edit_reason


def test_flag_stale_open_entries_marks_old_entry_and_skips_recent_one(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    stale_employee = make_employee(db_session, organization=org, department=department)
    recent_employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    now = datetime.now(timezone.utc)
    stale_entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=stale_employee,
        created_by=admin,
        started_at=now - timedelta(hours=20),
        ended_at=None,
        status="open",
    )
    recent_entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=recent_employee,
        created_by=admin,
        started_at=now - timedelta(hours=2),
        ended_at=None,
        status="open",
    )

    flagged_count = attendance_service.flag_stale_open_entries(cutoff_hours=16)

    db_session.refresh(stale_entry)
    db_session.refresh(recent_entry)
    assert flagged_count == 1
    assert stale_entry.status == "needs_review"
    assert stale_entry.ended_at is None
    assert recent_entry.status == "open"


def test_list_entries_scopes_by_role(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    other_employee = make_employee(db_session, organization=org, department=other_dept)
    admin = make_user(db_session, organization=org, role="admin")

    managed_entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )
    make_attendance_entry(
        db_session,
        organization=org,
        employee=other_employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    assert len(attendance_service.list_entries(admin_scope, date(2025, 12, 31), date(2026, 1, 2))) == 2

    manager = make_user(db_session, organization=org, role="manager")
    manager_scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )
    manager_results = attendance_service.list_entries(
        manager_scope, date(2025, 12, 31), date(2026, 1, 2)
    )
    assert [e.id for e in manager_results] == [managed_entry.id]

    employee_scope = _scope("employee", org.id, employee_id=employee.id)
    employee_results = attendance_service.list_entries(
        employee_scope, date(2025, 12, 31), date(2026, 1, 2)
    )
    assert [e.id for e in employee_results] == [managed_entry.id]
