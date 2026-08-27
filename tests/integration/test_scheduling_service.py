"""Integration tests for app.services.scheduling — DB + authorization."""

from datetime import date, datetime, timezone

import pytest
from werkzeug.exceptions import Forbidden, NotFound

from app.auth.scope import AccessScope
from app.services import departments as department_service
from app.services import scheduling as scheduling_service
from app.services.errors import ValidationError
from tests.factories import (
    make_department,
    make_employee,
    make_leave_request,
    make_leave_type,
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


def test_admin_creates_a_draft_shift_scoped_to_their_organization(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    shift = scheduling_service.create_shift(
        _scope("admin", org.id, user_id=admin.id),
        department_id=department.id,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
    )

    assert shift.organization_id == org.id
    assert shift.status == "draft"
    assert shift.business_date == date(2026, 1, 1)
    assert shift.created_by_user_id == admin.id


def test_create_shift_localizes_a_naive_datetime_to_the_organization_timezone(
    db_session,
):
    org = make_organization(db_session, timezone="America/New_York")
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    # 22:00 naive, interpreted as 22:00 America/New_York (UTC-5 in
    # January), still attributed to the start date per confirmed rule A1.
    shift = scheduling_service.create_shift(
        _scope("admin", org.id, user_id=admin.id),
        department_id=department.id,
        starts_at=datetime(2026, 1, 1, 22, 0),
        ends_at=datetime(2026, 1, 2, 6, 0),
    )

    assert shift.starts_at.tzinfo is not None
    assert shift.business_date == date(2026, 1, 1)


def test_manager_cannot_create_a_shift_in_an_unmanaged_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager")

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(Forbidden):
        scheduling_service.create_shift(
            scope,
            department_id=other_dept.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )


def test_employee_role_cannot_create_a_shift(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(Forbidden):
        scheduling_service.create_shift(
            scope,
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )


def test_create_shift_rejects_an_employee_from_another_organization(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    foreign_employee = make_employee(db_session, organization=other_org)
    admin = make_user(db_session, organization=org, role="admin")

    with pytest.raises(ValidationError):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=foreign_employee.id,
        )


def test_create_shift_rejects_an_overlapping_assignment(db_session):
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
        business_date=date(2026, 1, 1),
    )

    with pytest.raises(ValidationError):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_update_shift_rejects_editing_a_published_shift(db_session):
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
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ValidationError):
        scheduling_service.update_shift(
            _scope("admin", org.id, user_id=admin.id), shift.id, notes="changed"
        )


def test_update_shift_rejects_an_unknown_field(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(db_session, organization=org, department=department, created_by=admin)

    with pytest.raises(ValidationError):
        scheduling_service.update_shift(
            _scope("admin", org.id, user_id=admin.id), shift.id, employee_id=999
        )


def test_manager_cannot_update_a_shift_in_an_unmanaged_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager")
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(db_session, organization=org, department=other_dept, created_by=admin)

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(NotFound):
        scheduling_service.update_shift(scope, shift.id, notes="hacked")


def test_update_shift_recomputes_business_date_when_times_change(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session,
        organization=org,
        department=department,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    updated = scheduling_service.update_shift(
        _scope("admin", org.id, user_id=admin.id),
        shift.id,
        starts_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
    )

    assert updated.business_date == date(2026, 1, 5)


def test_assign_employee_rejects_an_employee_from_another_organization(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    foreign_employee = make_employee(db_session, organization=other_org)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(db_session, organization=org, department=department, created_by=admin)

    with pytest.raises(ValidationError):
        scheduling_service.assign_employee(
            _scope("admin", org.id, user_id=admin.id), shift.id, foreign_employee.id
        )


def test_manager_cannot_assign_an_employee_outside_their_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee_in_other_dept = make_employee(db_session, organization=org, department=other_dept)
    manager = make_user(db_session, organization=org, role="manager")
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session, organization=org, department=managed_dept, created_by=admin
    )

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(ValidationError):
        scheduling_service.assign_employee(scope, shift.id, employee_in_other_dept.id)


def test_assign_employee_rejects_a_cancelled_shift(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session,
        organization=org,
        department=department,
        created_by=admin,
        status="cancelled",
    )

    with pytest.raises(ValidationError):
        scheduling_service.assign_employee(
            _scope("admin", org.id, user_id=admin.id), shift.id, employee.id
        )


def test_publish_shift_requires_an_assigned_employee(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(db_session, organization=org, department=department, created_by=admin)

    with pytest.raises(ValidationError):
        scheduling_service.publish_shift(_scope("admin", org.id, user_id=admin.id), shift.id)


def test_publish_shift_sets_status_and_published_at(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session, organization=org, department=department, employee=employee, created_by=admin
    )

    published = scheduling_service.publish_shift(
        _scope("admin", org.id, user_id=admin.id), shift.id
    )

    assert published.status == "published"
    assert published.published_at is not None


def test_create_shift_rejects_an_end_before_start_with_a_clear_message(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    with pytest.raises(ValidationError, match="End time must be after the start time"):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        )


def test_create_shift_rejects_a_break_at_least_as_long_as_the_shift(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    with pytest.raises(ValidationError, match="Break time cannot be"):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            break_minutes=480,
        )


def test_create_shift_rejects_a_shift_longer_than_24_hours(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    with pytest.raises(ValidationError, match="cannot be longer than 24 hours"):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 2, 9, 1, tzinfo=timezone.utc),
        )


def test_create_shift_rejects_a_deactivated_department(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    scope = _scope("admin", org.id, user_id=admin.id)
    department_service.deactivate_department(scope, department.id)

    with pytest.raises(ValidationError):
        scheduling_service.create_shift(
            scope,
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )


def test_update_shift_allows_unrelated_edits_while_in_a_deactivated_department(
    db_session,
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    scope = _scope("admin", org.id, user_id=admin.id)
    shift = make_shift(
        db_session, organization=org, department=department, created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1), status="draft",
    )
    department_service.deactivate_department(scope, department.id)

    updated = scheduling_service.update_shift(
        scope, shift.id, department_id=department.id, notes="Updated."
    )

    assert updated.notes == "Updated."


def test_create_shift_rejects_a_shift_over_approved_leave(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    leave_type = make_leave_type(db_session, organization=org)
    make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type,
        requested_by=admin, status="approved",
        decided_by_user_id=admin.id, decided_at=datetime.now(timezone.utc),
        starts_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc),
    )

    with pytest.raises(ValidationError):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_publish_shift_rejects_a_draft_shift_over_leave_approved_after_creation(db_session):
    """Data/business-logic finding: the leave-conflict check on the shift
    side only ever runs at create/update/assign time, and the check on
    the leave side (leave.conflicting_shifts_for) only looks at already-
    *published* shifts — so a draft shift created before the employee's
    leave was approved could previously slip past every earlier check
    and still get published squarely on top of that approved leave.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session, organization=org, department=department, employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1), status="draft",
    )
    leave_type = make_leave_type(db_session, organization=org)
    # Constructed directly (bypassing approve_leave's own conflict check,
    # which only ever sees *published* shifts) purely to reach the state
    # this draft shift's later publish must itself now refuse.
    make_leave_request(
        db_session, organization=org, employee=employee, leave_type=leave_type,
        requested_by=admin, status="approved",
        decided_by_user_id=admin.id, decided_at=datetime.now(timezone.utc),
        starts_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc),
    )

    with pytest.raises(ValidationError):
        scheduling_service.publish_shift(_scope("admin", org.id, user_id=admin.id), shift.id)

    db_session.refresh(shift)
    assert shift.status == "draft"


def test_cancel_shift_sets_status_and_clears_published_at(db_session):
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
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    cancelled = scheduling_service.cancel_shift(
        _scope("admin", org.id, user_id=admin.id), shift.id
    )

    assert cancelled.status == "cancelled"
    assert cancelled.published_at is None


def test_cancel_shift_rejects_an_already_cancelled_shift(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    shift = make_shift(
        db_session, organization=org, department=department, created_by=admin, status="cancelled"
    )

    with pytest.raises(ValidationError):
        scheduling_service.cancel_shift(_scope("admin", org.id, user_id=admin.id), shift.id)


def test_list_shifts_scopes_by_role(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    admin = make_user(db_session, organization=org, role="admin")

    managed_shift = make_shift(
        db_session,
        organization=org,
        department=managed_dept,
        employee=employee,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    make_shift(
        db_session,
        organization=org,
        department=other_dept,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    admin_results = scheduling_service.list_shifts(
        admin_scope, date(2025, 12, 31), date(2026, 1, 2)
    )
    assert len(admin_results) == 2

    manager = make_user(db_session, organization=org, role="manager")
    manager_scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )
    manager_results = scheduling_service.list_shifts(
        manager_scope, date(2025, 12, 31), date(2026, 1, 2)
    )
    assert [s.id for s in manager_results] == [managed_shift.id]

    employee_scope = _scope("employee", org.id, employee_id=employee.id)
    employee_results = scheduling_service.list_shifts(
        employee_scope, date(2025, 12, 31), date(2026, 1, 2)
    )
    assert [s.id for s in employee_results] == [managed_shift.id]


def test_employee_does_not_see_draft_shifts_on_their_own_schedule(db_session):
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
        business_date=date(2026, 1, 1),
        status="draft",
    )

    employee_scope = _scope("employee", org.id, employee_id=employee.id)
    results = scheduling_service.list_shifts(
        employee_scope, date(2025, 12, 31), date(2026, 1, 2)
    )
    assert results == []


def test_coverage_summary_counts_published_shifts_and_active_employees(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee_a = make_employee(db_session, organization=org, department=department)
    make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    make_shift(
        db_session,
        organization=org,
        department=department,
        employee=employee_a,
        created_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    summary = scheduling_service.coverage_summary(
        _scope("admin", org.id, user_id=admin.id), department.id, date(2026, 1, 1)
    )

    assert summary == {"published_shifts": 1, "active_employees": 2}


def test_create_shift_rejects_a_terminated_employee(db_session):
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

    with pytest.raises(ValidationError):
        scheduling_service.create_shift(
            _scope("admin", org.id, user_id=admin.id),
            department_id=department.id,
            starts_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 2, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_assign_employee_rejects_a_terminated_employee(db_session):
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
    shift = make_shift(db_session, organization=org, department=department, created_by=admin)

    with pytest.raises(ValidationError):
        scheduling_service.assign_employee(
            _scope("admin", org.id, user_id=admin.id), shift.id, employee.id
        )


def test_terminating_an_employee_does_not_touch_their_existing_shift(db_session):
    """Fix 1 only blocks *new* assignment — an employee's shift history
    must survive being terminated afterward untouched (no retroactive
    invalidation of prior records).
    """
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
        status="published",
        published_at=datetime.now(timezone.utc),
    )

    employee.employment_status = "terminated"
    employee.terminated_on = date(2026, 1, 1)
    db_session.flush()

    db_session.refresh(shift)
    assert shift.employee_id == employee.id
    assert shift.status == "published"


def test_manager_cannot_view_coverage_for_an_unmanaged_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager")

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(Forbidden):
        scheduling_service.coverage_summary(scope, other_dept.id, date(2026, 1, 1))


class TestListShiftsEmployeeFilter:
    def test_admin_employee_filter_returns_only_that_employees_shifts(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee_a = make_employee(db_session, organization=org, department=department)
        employee_b = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        shift_a = make_shift(
            db_session, organization=org, department=department, employee=employee_a,
            created_by=admin, business_date=date(2024, 1, 1),
        )
        make_shift(
            db_session, organization=org, department=department, employee=employee_b,
            created_by=admin, business_date=date(2024, 1, 1),
        )

        results = scheduling_service.list_shifts(
            _scope("admin", org.id), date(2024, 1, 1), date(2024, 1, 1),
            employee_id=employee_a.id,
        )

        assert [shift.id for shift in results] == [shift_a.id]

    def test_manager_employee_filter_composes_with_department_scoping(self, db_session):
        org = make_organization(db_session)
        managed = make_department(db_session, organization=org)
        unmanaged = make_department(db_session, organization=org)
        managed_employee = make_employee(db_session, organization=org, department=managed)
        unmanaged_employee = make_employee(db_session, organization=org, department=unmanaged)
        admin = make_user(db_session, organization=org, role="admin")
        make_shift(
            db_session, organization=org, department=managed, employee=managed_employee,
            created_by=admin, business_date=date(2024, 1, 1),
        )
        make_shift(
            db_session, organization=org, department=unmanaged, employee=unmanaged_employee,
            created_by=admin, business_date=date(2024, 1, 1),
        )
        manager_scope = _scope(
            "manager", org.id, department_ids=frozenset({managed.id})
        )

        # A manager passing an out-of-department employee id must get an
        # empty intersection, never that employee's shifts.
        results = scheduling_service.list_shifts(
            manager_scope, date(2024, 1, 1), date(2024, 1, 1),
            employee_id=unmanaged_employee.id,
        )

        assert results == []


class TestScheduledHours:
    def test_subtracts_break_minutes_from_the_duration(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        shift = make_shift(
            db_session, organization=org, department=department, created_by=admin,
            starts_at=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2024, 1, 1, 17, 0, tzinfo=timezone.utc),
            break_minutes=30,
        )

        assert scheduling_service.scheduled_hours(shift) == pytest.approx(7.5)

    def test_zero_break_minutes_is_the_full_span(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        shift = make_shift(
            db_session, organization=org, department=department, created_by=admin,
            starts_at=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            break_minutes=0,
        )

        assert scheduling_service.scheduled_hours(shift) == pytest.approx(3.0)
