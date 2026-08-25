"""DB-level constraint coverage for the ``leave_types``/``leave_requests``
tables.

These exercise constraints directly against the model (bypassing the
service layer) to confirm the database itself — not just application
code — protects these invariants, same style as
``test_shift_constraints.py``/``test_attendance_constraints.py``.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.leave_request import LeaveRequest
from tests.factories import (
    make_employee,
    make_leave_request,
    make_leave_type,
    make_organization,
    make_user,
)

pytestmark = pytest.mark.integration


def _leave_request_kwargs(org, employee, leave_type, requested_by, **overrides):
    defaults = {
        "organization_id": org.id,
        "employee_id": employee.id,
        "leave_type_id": leave_type.id,
        "starts_at": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        "ends_at": datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        "status": "pending",
        "requested_by_user_id": requested_by.id,
    }
    defaults.update(overrides)
    return defaults


def test_exclusion_constraint_rejects_overlapping_pending_leave_for_same_employee(
    db_session,
):
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
        status="pending",
    )

    overlapping = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            starts_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(overlapping)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_exclusion_constraint_rejects_overlapping_approved_leave_for_same_employee(
    db_session,
):
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
        status="approved",
        decided_by_user_id=admin.id,
        decided_at=datetime.now(timezone.utc),
    )

    overlapping = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            starts_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(overlapping)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_cancelled_leave_request_does_not_block_a_new_overlapping_request(db_session):
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
        status="cancelled",
    )

    overlapping = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(overlapping)

    db_session.flush()  # must not raise: the existing request is cancelled


def test_rejected_leave_request_does_not_block_a_new_overlapping_request(db_session):
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
        status="rejected",
        decided_by_user_id=admin.id,
        decided_at=datetime.now(timezone.utc),
    )

    overlapping = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(overlapping)

    db_session.flush()  # must not raise: the existing request was rejected


def test_ends_at_before_starts_at_is_rejected(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            starts_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(leave_request)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_approved_status_requires_decision_fields(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(
            org, employee, leave_type, admin, status="approved"
        )
    )
    db_session.add(leave_request)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_pending_status_rejects_decision_fields(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            status="pending",
            decided_by_user_id=admin.id,
            decided_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(leave_request)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_cancelled_status_permits_carried_over_decision_fields(db_session):
    """A previously-approved request that gets cancelled keeps its
    decision fields (see app.models.leave_request's module docstring) —
    this is what makes it distinguishable from a pending-then-cancelled
    request using only the status column.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            status="cancelled",
            decided_by_user_id=admin.id,
            decided_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(leave_request)

    db_session.flush()  # must not raise


def test_cancelled_status_permits_no_decision_fields(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(org, employee, leave_type, admin, status="cancelled")
    )
    db_session.add(leave_request)

    db_session.flush()  # must not raise


def test_decision_fields_must_be_paired(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    leave_type = make_leave_type(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(
            org,
            employee,
            leave_type,
            admin,
            status="cancelled",
            decided_by_user_id=admin.id,
            decided_at=None,
        )
    )
    db_session.add(leave_request)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_employee_from_another_organization_is_rejected(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    employee_in_org_b = make_employee(db_session, organization=org_b)
    leave_type = make_leave_type(db_session, organization=org_a)
    admin = make_user(db_session, organization=org_a, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(org_a, employee_in_org_b, leave_type, admin)
    )
    db_session.add(leave_request)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_leave_type_from_another_organization_is_rejected(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    employee = make_employee(db_session, organization=org_a)
    leave_type_in_org_b = make_leave_type(db_session, organization=org_b)
    admin = make_user(db_session, organization=org_a, role="admin")

    leave_request = LeaveRequest(
        **_leave_request_kwargs(org_a, employee, leave_type_in_org_b, admin)
    )
    db_session.add(leave_request)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
