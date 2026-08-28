"""True multi-connection concurrency coverage for the DB's overlap/
duplicate-prevention guarantees.

Every race-prone invariant in this codebase (no duplicate open attendance
entry per employee, no overlapping shifts/attendance/leave per employee)
is enforced by a real PostgreSQL constraint — see
``app.models.attendance_entry``/``leave_request``/``shift`` — and every
service module translates the resulting ``IntegrityError`` into a clean
``ValidationError`` (see ``app.services.attendance._flush_or_raise`` and
its siblings in ``leave``/``scheduling``). Every existing constraint test
(``test_attendance_constraints.py`` and friends) only ever proves this
sequentially, within the single already-open, savepoint-isolated
transaction ``tests/conftest.py``'s ``db_session`` fixture provides: a
*later* insert conflicting with an earlier, still-uncommitted one in the
*same* transaction. That is a real but weaker guarantee than "two
genuinely independent, simultaneously-committing transactions cannot both
win" — this module proves the latter, using
``tests/integration/conftest.py``'s ``concurrent_db_sessions`` fixture
(two real connections, each able to commit for real) and
``concurrent.futures.ThreadPoolExecutor`` + ``threading.Barrier`` to fire
both sides at (as close as possible to) the same instant.

Direct-model inserts, not the service layer (a deliberate choice, for two
concrete reasons found during development, not just convenience):

1. The attendance race must assert the *exact* constraint name on the
   raised ``IntegrityError`` (``orig.diag.constraint_name`` — mirroring
   ``attendance.py``'s own ``_flush_or_raise`` pattern), to prove it's
   genuinely the open-entry unique index doing the work, not some other
   check. Driving the race through ``attendance.clock_in`` would swallow
   that raw ``IntegrityError`` into a translated ``ValidationError``
   inside the service function itself, making the exact-constraint
   assertion impossible without re-implementing the translation logic
   here just to unwrap it again.
2. Confirmed empirically while writing this suite: this environment's
   Python (3.14) does *not* propagate the submitting thread's
   ``contextvars`` context into ``ThreadPoolExecutor`` workers (a real
   behavior difference from earlier CPython versions — its
   ``concurrent.futures.thread`` no longer runs worker tasks via
   ``contextvars.Context.run`` at all). Driving a race through the
   service layer would need each worker to explicitly push its own
   ``app.app_context()`` and build its own ``AccessScope`` — doable, but
   meaningfully more moving parts than this phase's actual target (the
   database constraint, not the service layer's translation of it, which
   already has direct unit/integration coverage elsewhere). Direct-model
   inserts, mirroring ``test_attendance_constraints.py``'s existing
   style, keep the race itself the only new variable.

The leave race is at *request* time, not approval time (the task's own
suggested alternative) — deliberately, not by default: the exclusion
constraint's own ``WHERE status IN ('pending', 'approved')`` clause
already covers a merely-*pending* request, so two overlapping requests
for the same employee can never both exist in the first place, even
before either is approved. A second, overlapping request is already
rejected at creation. There is no separate "approval-time" race to prove
here — approving one of two already-coexisting overlapping requests is
impossible by construction, so creation is the only real race window.

A genuine, documented PostgreSQL behavior surfaced while developing the
leave/shift tests: concurrent inserts of overlapping ranges into a table
with a GiST exclusion constraint can occasionally deadlock
(``psycopg.errors.DeadlockDetected``, SQLSTATE ``40P01``) instead of one
side cleanly blocking, then failing with a constraint violation, once the
other commits. This was reproduced directly (both the leave and shift
races hit it in roughly 1 out of every 10-15 barrier-synchronized runs
during manual verification). It is not a bug in this codebase's
constraints or this test — it's how PostgreSQL's GiST index locking
works under truly simultaneous conflicting inserts. Either outcome is a
legitimate proof that the database stopped the race (Postgres either
rejects the loser outright, or kills one side as a deadlock victim so the
other can proceed) so both are accepted as passing, via
``_assert_exactly_one_side_won`` below, keeping the test deterministic
without weakening what it proves: exactly one side ever wins, never both,
never neither.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.attendance_entry import AttendanceEntry
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.organization import Organization
from app.models.shift import Shift
from app.models.user import User
from tests.factories import (
    make_department,
    make_employee,
    make_leave_type,
    make_organization,
    make_user,
)

pytestmark = pytest.mark.integration

_BARRIER_TIMEOUT_SECONDS = 10
_FUTURE_TIMEOUT_SECONDS = 15

# SQLSTATE for a deadlock, as opposed to a plain constraint violation —
# see the module docstring for why this is an accepted outcome for the
# two GiST-exclusion-constraint-backed races below.
_DEADLOCK_SQLSTATE = "40P01"


def _constraint_name(error: IntegrityError) -> str | None:
    """Mirrors the exact constraint-name-matching pattern every service
    module's ``_flush_or_raise``/``_commit_or_raise_overlap`` uses (see
    e.g. ``app.services.attendance._flush_or_raise``).
    """
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def _is_deadlock(error: OperationalError) -> bool:
    return getattr(error.orig, "sqlstate", None) == _DEADLOCK_SQLSTATE


def _assert_exactly_one_side_won(results: list[tuple[str, object]], expected_constraint: str) -> None:
    """Shared assertion for all three races below.

    ``results`` is a list of two ``(outcome, error_or_none)`` pairs, one
    per racing thread. Exactly one side must have succeeded; the other
    must have failed either with the expected constraint violation, or
    (GiST-backed races only) a deadlock — see the module docstring.
    """
    outcomes = [outcome for outcome, _ in results]
    assert outcomes.count("success") == 1, (
        f"expected exactly one side to win the race, got outcomes {outcomes}"
    )

    losing_outcome, losing_error = next(
        (outcome, error) for outcome, error in results if outcome != "success"
    )
    if losing_outcome == "integrity_error":
        assert _constraint_name(losing_error) == expected_constraint, (
            f"expected the losing side to fail on {expected_constraint!r}, "
            f"got {_constraint_name(losing_error)!r}"
        )
    else:
        assert losing_outcome == "deadlock", f"unexpected outcome: {losing_outcome!r}"


def _cleanup_organization(session: Session, organization_id: int) -> None:
    """Delete every row this suite may have created for ``organization_id``.

    These tests bypass ``db_session``'s automatic rollback (see
    ``tests/integration/conftest.py``), so every row created through
    ``concurrent_db_sessions`` is real and must be cleaned up explicitly,
    or it would linger and could confuse another test's assumptions about
    a clean database (e.g. an organization-scoped uniqueness check).
    Deletes are ordered so a child row is always removed before the
    parent row it references — every foreign key in this codebase is
    ``ondelete="RESTRICT"`` (see ``.claude/rules/database.md``), so
    deleting in the wrong order would raise a real ``IntegrityError``
    here in cleanup, not just silently cascade.
    """
    session.query(AttendanceEntry).filter(
        AttendanceEntry.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(LeaveRequest).filter(
        LeaveRequest.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(Shift).filter(
        Shift.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(LeaveType).filter(
        LeaveType.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(User).filter(
        User.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(Employee).filter(
        Employee.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(Department).filter(
        Department.organization_id == organization_id
    ).delete(synchronize_session=False)
    session.query(Organization).filter(Organization.id == organization_id).delete(
        synchronize_session=False
    )
    session.commit()


def test_two_concurrent_clock_ins_for_the_same_employee_exactly_one_succeeds(
    concurrent_db_sessions,
):
    """The actual duplicate-clock-in guarantee
    (``uq_attendance_entries_employee_id_open``) must hold across two
    genuinely independent, simultaneously-committing transactions, not
    just within one shared transaction (see module docstring).
    """
    session_a, session_b = concurrent_db_sessions

    organization = make_organization(session_a)
    department = make_department(session_a, organization=organization)
    employee = make_employee(session_a, organization=organization, department=department)
    admin = make_user(session_a, organization=organization, role="admin")
    session_a.commit()

    organization_id, employee_id, admin_id = organization.id, employee.id, admin.id
    barrier = threading.Barrier(2, timeout=_BARRIER_TIMEOUT_SECONDS)

    def _attempt_open_clock_in(session: Session, minute: int) -> tuple[str, object]:
        entry = AttendanceEntry(
            organization_id=organization_id,
            employee_id=employee_id,
            shift_id=None,
            started_at=datetime(2026, 5, 1, 9, minute, tzinfo=timezone.utc),
            ended_at=None,
            business_date=date(2026, 5, 1),
            break_minutes=0,
            status="open",
            source="web",
            created_by_user_id=admin_id,
        )
        session.add(entry)
        barrier.wait()
        try:
            session.commit()
            return ("success", None)
        except IntegrityError as error:
            session.rollback()
            return ("integrity_error", error)
        except OperationalError as error:
            session.rollback()
            if not _is_deadlock(error):
                raise
            return ("deadlock", error)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(_attempt_open_clock_in, session_a, 0)
            future_b = executor.submit(_attempt_open_clock_in, session_b, 1)
            results = [
                future_a.result(timeout=_FUTURE_TIMEOUT_SECONDS),
                future_b.result(timeout=_FUTURE_TIMEOUT_SECONDS),
            ]

        _assert_exactly_one_side_won(
            results, expected_constraint="uq_attendance_entries_employee_id_open"
        )
    finally:
        _cleanup_organization(session_a, organization_id)


def test_two_concurrent_overlapping_leave_requests_for_the_same_employee_exactly_one_succeeds(
    concurrent_db_sessions,
):
    """``ex_leave_requests_employee_no_overlap`` must hold across two
    genuinely independent, simultaneously-committing transactions — see
    the module docstring for why this races at request-creation time,
    not approval time, and why a deadlock is an accepted outcome here.
    """
    session_a, session_b = concurrent_db_sessions

    organization = make_organization(session_a)
    department = make_department(session_a, organization=organization)
    employee = make_employee(session_a, organization=organization, department=department)
    admin = make_user(session_a, organization=organization, role="admin")
    leave_type = make_leave_type(session_a, organization=organization)
    session_a.commit()

    organization_id = organization.id
    employee_id = employee.id
    admin_id = admin.id
    leave_type_id = leave_type.id
    barrier = threading.Barrier(2, timeout=_BARRIER_TIMEOUT_SECONDS)

    def _attempt_overlapping_request(session: Session, start_hour: int) -> tuple[str, object]:
        # An 8-hour window starting at 09:00 or 11:00 on the same day
        # always overlaps (09:00-17:00 vs 11:00-19:00).
        leave_request = LeaveRequest(
            organization_id=organization_id,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            starts_at=datetime(2026, 6, 1, start_hour, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 6, 1, start_hour + 8, 0, tzinfo=timezone.utc),
            status="pending",
            requested_by_user_id=admin_id,
        )
        session.add(leave_request)
        barrier.wait()
        try:
            session.commit()
            return ("success", None)
        except IntegrityError as error:
            session.rollback()
            return ("integrity_error", error)
        except OperationalError as error:
            session.rollback()
            if not _is_deadlock(error):
                raise
            return ("deadlock", error)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(_attempt_overlapping_request, session_a, 9)
            future_b = executor.submit(_attempt_overlapping_request, session_b, 11)
            results = [
                future_a.result(timeout=_FUTURE_TIMEOUT_SECONDS),
                future_b.result(timeout=_FUTURE_TIMEOUT_SECONDS),
            ]

        _assert_exactly_one_side_won(
            results, expected_constraint="ex_leave_requests_employee_no_overlap"
        )
    finally:
        _cleanup_organization(session_a, organization_id)


def test_two_concurrent_overlapping_shift_assignments_for_the_same_employee_exactly_one_succeeds(
    concurrent_db_sessions,
):
    """``ex_shifts_employee_no_overlap`` must hold across two genuinely
    independent, simultaneously-committing transactions — the same real
    scenario as two schedulers concurrently assigning one employee to two
    different, overlapping open shifts. A deadlock is an accepted
    outcome here too, for the same GiST-exclusion-constraint reason as
    the leave race (see module docstring).
    """
    session_a, session_b = concurrent_db_sessions

    organization = make_organization(session_a)
    department = make_department(session_a, organization=organization)
    employee = make_employee(session_a, organization=organization, department=department)
    admin = make_user(session_a, organization=organization, role="admin")
    session_a.commit()

    organization_id = organization.id
    department_id = department.id
    employee_id = employee.id
    admin_id = admin.id
    barrier = threading.Barrier(2, timeout=_BARRIER_TIMEOUT_SECONDS)

    def _attempt_overlapping_shift(session: Session, start_hour: int) -> tuple[str, object]:
        # An 8-hour shift starting at 09:00 or 11:00 on the same day
        # always overlaps (09:00-17:00 vs 11:00-19:00).
        shift = Shift(
            organization_id=organization_id,
            department_id=department_id,
            employee_id=employee_id,
            starts_at=datetime(2026, 7, 1, start_hour, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 7, 1, start_hour + 8, 0, tzinfo=timezone.utc),
            business_date=date(2026, 7, 1),
            break_minutes=0,
            status="draft",
            created_by_user_id=admin_id,
        )
        session.add(shift)
        barrier.wait()
        try:
            session.commit()
            return ("success", None)
        except IntegrityError as error:
            session.rollback()
            return ("integrity_error", error)
        except OperationalError as error:
            session.rollback()
            if not _is_deadlock(error):
                raise
            return ("deadlock", error)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(_attempt_overlapping_shift, session_a, 9)
            future_b = executor.submit(_attempt_overlapping_shift, session_b, 11)
            results = [
                future_a.result(timeout=_FUTURE_TIMEOUT_SECONDS),
                future_b.result(timeout=_FUTURE_TIMEOUT_SECONDS),
            ]

        _assert_exactly_one_side_won(
            results, expected_constraint="ex_shifts_employee_no_overlap"
        )
    finally:
        _cleanup_organization(session_a, organization_id)
