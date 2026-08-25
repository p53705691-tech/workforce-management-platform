"""DB-level constraint coverage for the ``attendance_entries`` table.

These exercise constraints directly against the model (bypassing the
service layer) to confirm the database itself — not just application
code — protects these invariants, mirroring
tests/integration/test_shift_constraints.py's approach for shifts. The
partial unique index (at most one open entry per employee) is the single
most important test in this milestone: it is the actual duplicate-
clock-in guarantee, not just an application-level check.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.attendance_entry import AttendanceEntry
from tests.factories import make_attendance_entry, make_employee, make_organization, make_user

pytestmark = pytest.mark.integration


def _entry_kwargs(org, employee, created_by=None, **overrides):
    defaults = {
        "organization_id": org.id,
        "employee_id": employee.id,
        "shift_id": None,
        "started_at": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        "ended_at": datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        "business_date": date(2026, 1, 1),
        "break_minutes": 0,
        "status": "closed",
        "source": "web",
        "created_by_user_id": created_by.id if created_by else None,
    }
    defaults.update(overrides)
    return defaults


def test_partial_unique_index_rejects_a_second_open_entry_for_the_same_employee(
    db_session,
):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ended_at=None,
        status="open",
    )

    second_open_entry = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            started_at=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
            ended_at=None,
            status="open",
        )
    )
    db_session.add(second_open_entry)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_exclusion_constraint_rejects_an_overlapping_entry(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
    )

    overlapping = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(overlapping)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_duration_max_24_hours_check_rejects_an_overlong_entry(db_session):
    """Round B fix: attendance_entries now has the same 24-hour duration
    cap as shifts (``duration_max_24_hours``), enforced at the DB level
    so an overlong entry can never slip through even if application code
    were bypassed.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    overlong = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            started_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc),
        )
    )
    db_session.add(overlong)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_open_entry_blocks_a_later_entry_from_being_inserted(db_session):
    """An unbounded range still intersects: an open entry (no ended_at)
    must block any later entry for the same employee, not just ones that
    literally overlap a bounded window.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        ended_at=None,
        status="open",
    )

    later = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
            status="closed",
        )
    )
    db_session.add(later)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_status_open_requires_ended_at_null(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    entry = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            status="open",
            ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(entry)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_status_closed_requires_ended_at_not_null(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    entry = AttendanceEntry(
        **_entry_kwargs(org, employee, admin, status="closed", ended_at=None)
    )
    db_session.add(entry)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_status_needs_review_is_allowed_with_ended_at_null(db_session):
    """Resolves a conflict in the spec: a stale open entry is flagged
    ``needs_review`` while ``ended_at`` stays NULL (rule A11 — never
    invent an end time). See app/models/attendance_entry.py's module
    docstring for the full explanation.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    entry = AttendanceEntry(
        **_entry_kwargs(org, employee, admin, status="needs_review", ended_at=None)
    )
    db_session.add(entry)

    db_session.flush()  # must not raise


def test_edited_by_user_id_alone_is_rejected(db_session):
    """These are split into separate tests (rather than one test with
    several sequential ``pytest.raises``/``rollback()`` cycles) because
    the test fixture's savepoint-based isolation rolls back *all*
    uncommitted work — including this test's own earlier factory
    inserts — on ``db_session.rollback()``, not just the failed insert.
    """
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    missing_both = AttendanceEntry(
        **_entry_kwargs(org, employee, admin, edited_by_user_id=admin.id)
    )
    db_session.add(missing_both)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_edited_by_user_id_with_edited_at_but_no_reason_is_rejected(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    missing_reason = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            edited_by_user_id=admin.id,
            edited_at=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(missing_reason)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_edited_by_user_id_with_edited_at_and_reason_is_accepted(db_session):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    complete_edit = AttendanceEntry(
        **_entry_kwargs(
            org,
            employee,
            admin,
            edited_by_user_id=admin.id,
            edited_at=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
            edit_reason="Employee forgot to clock out; corrected from timesheet.",
        )
    )
    db_session.add(complete_edit)

    db_session.flush()  # must not raise


def test_overnight_entry_is_stored_as_a_single_row_with_start_date_attribution(
    db_session,
):
    org = make_organization(db_session)
    employee = make_employee(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")

    entry = make_attendance_entry(
        db_session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=datetime(2026, 1, 1, 22, 10, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 2, 6, 5, tzinfo=timezone.utc),
        business_date=date(2026, 1, 1),
    )

    db_session.flush()
    fetched = db_session.get(AttendanceEntry, entry.id)
    assert fetched is not None
    assert fetched.started_at.hour == 22
    assert fetched.ended_at.day == 2
    assert fetched.business_date == date(2026, 1, 1)
    assert (
        db_session.query(AttendanceEntry)
        .filter(AttendanceEntry.employee_id == employee.id)
        .count()
        == 1
    )
