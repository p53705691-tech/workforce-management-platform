"""Integration tests for app.services.leave — DB + authorization."""

from datetime import date, datetime, timezone

import pytest
from werkzeug.exceptions import Forbidden, NotFound

from app.auth.scope import AccessScope
from app.services import leave as leave_service
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


def test_employee_requests_their_own_leave(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)

    scope = _scope("employee", org.id, employee_id=employee.id, user_id=user.id)
    leave_request = leave_service.request_leave(
        scope,
        leave_type_id=leave_type.id,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
    )

    assert leave_request.employee_id == employee.id
    assert leave_request.status == "pending"
    assert leave_request.requested_by_user_id == user.id


def test_employee_cannot_request_leave_on_behalf_of_another_employee(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)

    scope = _scope("employee", org.id, employee_id=employee.id, user_id=user.id)

    with pytest.raises(Forbidden):
        leave_service.request_leave(
            scope,
            leave_type_id=leave_type.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=other_employee.id,
        )


def test_manager_can_request_leave_for_an_employee_in_a_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    leave_type = make_leave_type(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager")

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )
    leave_request = leave_service.request_leave(
        scope,
        leave_type_id=leave_type.id,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        employee_id=employee.id,
    )

    assert leave_request.employee_id == employee.id


def test_manager_cannot_request_leave_for_an_employee_outside_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=other_dept)
    leave_type = make_leave_type(db_session, organization=org)
    manager = make_user(db_session, organization=org, role="manager")

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(ValidationError):
        leave_service.request_leave(
            scope,
            leave_type_id=leave_type.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_request_leave_rejects_a_terminated_employee(db_session):
    org = make_organization(db_session)
    employee = make_employee(
        db_session,
        organization=org,
        employment_status="terminated",
        terminated_on=date(2026, 1, 1),
    )
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        leave_service.request_leave(
            scope,
            leave_type_id=leave_type.id,
            starts_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 2, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_terminating_an_employee_does_not_touch_their_existing_leave_request(db_session):
    """Fix 1 only blocks a *new* leave request — an employee's leave
    history must survive being terminated afterward untouched.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        status="approved",
        decided_by_user_id=admin.id,
        decided_at=datetime.now(timezone.utc),
    )

    employee.employment_status = "terminated"
    employee.terminated_on = date(2026, 1, 1)
    db_session.flush()

    db_session.refresh(leave_request)
    assert leave_request.employee_id == employee.id
    assert leave_request.status == "approved"


def test_request_leave_rejects_a_leave_type_from_another_organization(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    foreign_leave_type = make_leave_type(db_session, organization=other_org)
    admin = make_user(db_session, organization=org, role="admin")

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        leave_service.request_leave(
            scope,
            leave_type_id=foreign_leave_type.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_request_leave_rejects_an_overlapping_pending_request(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
    )

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        leave_service.request_leave(
            scope,
            leave_type_id=leave_type.id,
            starts_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )


def test_approve_leave_is_blocked_by_a_conflicting_published_shift(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    leave_type = make_leave_type(db_session, organization=org)
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
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        starts_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        leave_service.approve_leave(scope, leave_request.id)

    db_session.refresh(leave_request)
    db_session.refresh(shift)
    assert leave_request.status == "pending"
    assert shift.status == "published"
    assert shift.employee_id == employee.id


def test_approve_leave_conflict_message_uses_organization_local_time(db_session):
    """Round C fix: the conflict message must render the shift's times in
    the organization's own timezone, not whatever offset the database
    session happens to attach on read-back for a raw timestamptz value —
    the same ambient-timezone problem app/__init__.py's local_dt Jinja
    filter exists to prevent for templates (see that filter's docstring).
    """
    org = make_organization(db_session, timezone="America/New_York")
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    # 09:00-17:00 UTC is 04:00-12:00 EST (America/New_York is UTC-5 in
    # January, outside DST) -- the conflict message must show the local
    # wall-clock hours, never the raw UTC ones.
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
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        starts_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError) as excinfo:
        leave_service.approve_leave(scope, leave_request.id)

    message = str(excinfo.value)
    assert "2026-01-01 04:00" in message
    assert "2026-01-01 12:00" in message
    # The raw UTC hours must never leak into the message either.
    assert "09:00" not in message
    assert "17:00" not in message


def test_approve_leave_succeeds_without_conflicting_shifts(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    approved = leave_service.approve_leave(scope, leave_request.id, decision_note="Approved.")

    assert approved.status == "approved"
    assert approved.decided_by_user_id == admin.id
    assert approved.decided_at is not None
    assert approved.decision_note == "Approved."


def test_admin_cannot_approve_their_own_leave_request(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin", employee_id=employee.id)
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("admin", org.id, employee_id=employee.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        leave_service.approve_leave(scope, leave_request.id)

    db_session.refresh(leave_request)
    assert leave_request.status == "pending"


def test_manager_cannot_approve_a_leave_request_outside_their_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=other_dept)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    manager = make_user(db_session, organization=org, role="manager")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )

    with pytest.raises(NotFound):
        leave_service.approve_leave(scope, leave_request.id)


def test_employee_cannot_approve_any_leave_request(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(Forbidden):
        leave_service.approve_leave(scope, leave_request.id)


def test_reject_leave_without_decision_note_is_rejected(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("admin", org.id, user_id=admin.id)

    with pytest.raises(ValidationError):
        leave_service.reject_leave(scope, leave_request.id, decision_note="   ")

    db_session.refresh(leave_request)
    assert leave_request.status == "pending"


def test_reject_leave_with_a_note_sets_decision_fields(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    rejected = leave_service.reject_leave(
        scope, leave_request.id, decision_note="Insufficient staffing on those dates."
    )

    assert rejected.status == "rejected"
    assert rejected.decided_by_user_id == admin.id
    assert rejected.decided_at is not None


def test_employee_can_cancel_their_own_pending_request(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("employee", org.id, employee_id=employee.id, user_id=user.id)
    cancelled = leave_service.cancel_leave(scope, leave_request.id)

    assert cancelled.status == "cancelled"


def test_employee_cannot_cancel_someone_elses_request(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=other_employee,
        leave_type=leave_type,
        requested_by=admin,
    )

    scope = _scope("employee", org.id, employee_id=employee.id)

    with pytest.raises(NotFound):
        leave_service.cancel_leave(scope, leave_request.id)


def test_employee_cannot_cancel_their_own_already_approved_request(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    user = make_user(db_session, organization=org, role="employee", employee_id=employee.id)
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        status="approved",
        decided_by_user_id=admin.id,
        decided_at=datetime.now(timezone.utc),
    )

    scope = _scope("employee", org.id, employee_id=employee.id, user_id=user.id)

    with pytest.raises(ValidationError):
        leave_service.cancel_leave(scope, leave_request.id)


def test_admin_can_cancel_an_already_approved_request_and_keeps_decision_fields(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    decided_at = datetime.now(timezone.utc)
    leave_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
        status="approved",
        decided_by_user_id=admin.id,
        decided_at=decided_at,
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    cancelled = leave_service.cancel_leave(scope, leave_request.id)

    assert cancelled.status == "cancelled"
    # The prior decision is preserved so an approved-then-cancelled
    # request stays distinguishable from a pending-then-cancelled one.
    assert cancelled.decided_by_user_id == admin.id
    assert cancelled.decided_at is not None


def test_list_leave_requests_scopes_by_role(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    other_employee = make_employee(db_session, organization=org, department=other_dept)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    managed_request = make_leave_request(
        db_session,
        organization=org,
        employee=employee,
        leave_type=leave_type,
        requested_by=admin,
    )
    make_leave_request(
        db_session,
        organization=org,
        employee=other_employee,
        leave_type=leave_type,
        requested_by=admin,
        starts_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 2, 1, 17, 0, tzinfo=timezone.utc),
    )

    admin_scope = _scope("admin", org.id, user_id=admin.id)
    assert len(leave_service.list_leave_requests(admin_scope)) == 2

    manager = make_user(db_session, organization=org, role="manager")
    manager_scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )
    manager_results = leave_service.list_leave_requests(manager_scope)
    assert [r.id for r in manager_results] == [managed_request.id]

    employee_scope = _scope("employee", org.id, employee_id=employee.id)
    employee_results = leave_service.list_leave_requests(employee_scope)
    assert [r.id for r in employee_results] == [managed_request.id]
