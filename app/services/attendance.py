"""Attendance service: business logic for clock-in/out and corrections.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, independent of whatever the route layer already
checked — same pattern as ``app.services.scheduling``/``employees``.

Ambiguities resolved during implementation (see the confirmed source of
truth precedence in CLAUDE.md — explicit requirements over invented
behavior):

- The spec does not explicitly say whether an employee clocking
  themselves out may set a custom ``at`` (only clock-in explicitly says
  "an employee can never backdate"). Treated identically to clock-in for
  consistency with the wider "an employee never sets their own historical
  times" principle used throughout this module — only admin/manager may
  pass a non-``None`` ``at`` to either ``clock_in`` or ``clock_out``.
- ``correct_entry``'s parameter list in the spec (``edit_reason`` last,
  without a default, after several defaulted parameters) is not valid
  Python. ``edit_reason`` is placed right after ``attendance_entry_id`` as
  a required positional/keyword argument instead — this keeps "required,
  no default" as an actual language-enforced guarantee rather than a
  convention that could be silently violated.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import abort
from sqlalchemy.exc import IntegrityError

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.attendance_entry import AttendanceEntry
from app.models.employee import Employee
from app.models.shift import Shift
from app.services import audit as audit_service
from app.services.errors import ValidationError
from app.services.scheduling import business_date_for, organization_timezone

# Per confirmed rule A3: a clock-in within 60 minutes of a published
# shift's start/end still counts as "working that shift" for automatic
# shift-matching purposes.
_SHIFT_MATCH_GRACE = timedelta(minutes=60)

# Round B decision (not specified anywhere else, chosen here): the widest
# a clock-in or a correction may set an entry's started_at into the past.
# 90 days comfortably covers a typical payroll correction/dispute window
# (most timesheet disputes surface well within one quarter) without
# leaving the guard so wide it's effectively meaningless -- the whole
# point is to bound how far back a colluding manager+employee (or a
# fat-fingered correction) can push a figure that flows straight into
# historical overtime/labor-cost calculations no one is likely to audit
# that far back. A named constant so this specific number is easy to
# find and reconsider later. No corresponding "future" constant: a
# clock-in/correction may never be dated in the future at all, not just
# "within some window" of it.
_MAX_BACKDATE = timedelta(days=90)

# Names of the DB's data-integrity guarantees for attendance_entries (see
# migration 0009_create_attendance_entries). Matched against
# IntegrityError.orig.diag so a race that slips past any best-effort
# in-app check still surfaces as a clean ValidationError, not a raw 500 —
# same pattern as app.services.scheduling's overlap handling.
_OPEN_ENTRY_UNIQUE_INDEX = "uq_attendance_entries_employee_id_open"
_OVERLAP_EXCLUSION_CONSTRAINT = "ex_attendance_entries_employee_no_overlap"
_ENDED_AFTER_STARTED_CHECK = "ck_attendance_entries_ended_after_started"
_BREAK_LESS_THAN_DURATION_CHECK = "ck_attendance_entries_break_minutes_less_than_duration"
_DURATION_MAX_24_HOURS_CHECK = "ck_attendance_entries_duration_max_24_hours"


def _localize(value: datetime, tz: ZoneInfo) -> datetime:
    """Interpret a naive ``value`` as wall-clock time in ``tz``.

    Mirrors ``app.services.scheduling._localize`` exactly (see that
    function's docstring for the rationale) — duplicated rather than
    imported since it's a private, per-module adapter, not a shared
    business rule like ``business_date_for``.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value


def _validate_employee_for_scope(scope: AccessScope, employee_id: int) -> Employee:
    """Confirm ``employee_id`` may be acted on (clocked in, clocked out,
    corrected) by the caller.

    The employee must belong to the caller's organization (the DB's
    composite FK is the actual authority; this turns a cross-tenant id
    into a clean ``ValidationError`` instead of a raw ``IntegrityError``).
    A manager may only act on employees in departments they manage.

    Only used by ``clock_in`` (creating a *new* attendance entry) — never
    by ``clock_out``/``correct_entry``, which act on an entry that already
    exists via ``_get_entry_for_scope`` instead, so a terminated
    employee's existing open entry can still be closed or corrected;
    only a brand-new clock-in is blocked, exactly like
    ``app.services.scheduling._validate_employee_assignable``.
    """
    employee = (
        db.session.query(Employee)
        .filter(
            Employee.id == employee_id,
            Employee.organization_id == scope.organization_id,
        )
        .first()
    )
    if employee is None:
        raise ValidationError(
            "Selected employee does not exist in this organization.",
            field="employee_id",
        )
    if scope.role == "manager" and employee.department_id not in scope.department_ids:
        raise ValidationError(
            "You may only act on employees in departments you manage.",
            field="employee_id",
        )
    if employee.employment_status != "active":
        raise ValidationError(
            "Only an active employee may clock in.",
            field="employee_id",
        )
    return employee


def _validate_started_at_window(started_at: datetime) -> None:
    """Bound how far ``started_at`` may be set from "now" (Round B fix).

    Applies to both ``clock_in`` and ``correct_entry`` — anywhere a
    caller sets an entry's ``started_at`` — since both are equally able
    to plant a bogus historical (or future) figure that then flows into
    overtime/labor-cost calculations.
    """
    now = datetime.now(timezone.utc)
    if started_at > now:
        raise ValidationError(
            "Clock-in time cannot be in the future.", field="started_at"
        )
    if now - started_at > _MAX_BACKDATE:
        raise ValidationError(
            f"Clock-in time cannot be more than {_MAX_BACKDATE.days} days "
            "in the past.",
            field="started_at",
        )


def _validate_ended_after_started(started_at: datetime, ended_at: datetime) -> None:
    """Reject a non-positive entry duration before it ever reaches the
    DB's own ``ck_attendance_entries_ended_after_started`` CHECK.

    Checked explicitly (not left to the DB constraint alone) because with
    a fresh entry's default ``break_minutes=0``, ``ck_attendance_entries_
    break_minutes_less_than_duration`` evaluates first for this exact
    case (``0 < a negative number`` is false) and reports a confusing
    "break too long" message for what is actually a clock-out-before-
    clock-in mistake — see ``app.services.scheduling._validate_ends_
    after_starts`` for the identical issue on the shift side.
    """
    if ended_at <= started_at:
        raise ValidationError(
            "Clock-out time must be after the clock-in time.", field="ended_at"
        )


def _validate_ended_at_not_in_future(ended_at: datetime) -> None:
    """Reject a clock-out/correction ``ended_at`` set in the future
    (security-review finding): unlike ``started_at``, this has no
    "how far back" bound — a past ``ended_at`` is exactly what closing an
    entry means — only "not later than now", since not-yet-worked time
    must never be fabricated into worked hours, overtime, or labor cost.
    Applies to both ``clock_out`` and ``correct_entry``, the only two
    places that set an entry's ``ended_at``.
    """
    if ended_at > datetime.now(timezone.utc):
        raise ValidationError(
            "Clock-out time cannot be in the future.", field="ended_at"
        )


def _get_entry_for_scope(scope: AccessScope, attendance_entry_id: int) -> AttendanceEntry:
    """Fetch an attendance entry constrained to ``scope``, or 404.

    ``AttendanceEntry`` has no ``department_id`` column of its own (unlike
    ``Shift``), so ``app.auth.scope.get_scoped_or_404``'s manager
    restriction doesn't apply automatically — the department check is
    done here via a join to the owning employee instead. A 404 (not 403)
    is returned for an out-of-scope entry, same IDOR defense used
    everywhere else in the project: a caller cannot distinguish "doesn't
    exist" from "exists but you can't see it".
    """
    entry = (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.id == attendance_entry_id,
            AttendanceEntry.organization_id == scope.organization_id,
        )
        .first()
    )
    if entry is None:
        abort(404)

    if scope.role == "employee":
        if entry.employee_id != scope.employee_id:
            abort(404)
    elif scope.role == "manager":
        employee = db.session.get(Employee, entry.employee_id)
        if employee is None or employee.department_id not in scope.department_ids:
            abort(404)

    return entry


def _flush_or_raise() -> None:
    """Flush the session, translating known constraint violations.

    A flush is enough to trigger these (all non-deferred) constraint
    checks without committing, so a caller that still needs to stage an
    audit entry afterward can do so and cover both in one final commit
    (see ``app.services.audit``'s module docstring).

    Any other ``IntegrityError`` is re-raised unchanged for the caller
    (route layer) to handle — same pattern as
    ``app.services.scheduling._commit_or_raise_overlap``.
    """
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        constraint_name = getattr(
            getattr(error.orig, "diag", None), "constraint_name", None
        )
        if constraint_name == _OPEN_ENTRY_UNIQUE_INDEX:
            raise ValidationError(
                "This employee already has an open attendance entry. "
                "Clock out first."
            ) from error
        if constraint_name == _OVERLAP_EXCLUSION_CONSTRAINT:
            raise ValidationError(
                "This attendance entry overlaps with an existing one for "
                "this employee."
            ) from error
        if constraint_name == _ENDED_AFTER_STARTED_CHECK:
            raise ValidationError(
                "Clock-out time must be after the clock-in time."
            ) from error
        if constraint_name == _BREAK_LESS_THAN_DURATION_CHECK:
            raise ValidationError(
                "Break time cannot be equal to or longer than the "
                "entry's duration.",
                field="break_minutes",
            ) from error
        if constraint_name == _DURATION_MAX_24_HOURS_CHECK:
            raise ValidationError(
                "This entry cannot span more than 24 hours.",
                field="ended_at",
            ) from error
        raise


def _commit_or_raise() -> None:
    """Flush (translating known constraint violations) then commit.

    Used by callers with no audit entry to stage alongside the primary
    write; ``correct_entry`` instead calls ``_flush_or_raise`` directly
    so it can stage its audit entry before the one commit that covers
    both.
    """
    _flush_or_raise()
    db.session.commit()


def _match_shift(organization_id: int, employee_id: int, at: datetime) -> int | None:
    """Find the single published shift this clock-in belongs to, if any.

    Per confirmed rule A3: a published shift's range is expanded by a
    60-minute grace window on both ends before checking whether it
    contains the clock-in instant. Zero or multiple candidates leave the
    entry unmatched (``shift_id`` stays NULL) rather than guessing.
    """
    candidates = (
        db.session.query(Shift)
        .filter(
            Shift.organization_id == organization_id,
            Shift.employee_id == employee_id,
            Shift.status == "published",
            Shift.starts_at <= at + _SHIFT_MATCH_GRACE,
            Shift.ends_at >= at - _SHIFT_MATCH_GRACE,
        )
        .all()
    )
    if len(candidates) == 1:
        return candidates[0].id
    return None


def clock_in(
    scope: AccessScope, employee_id: int | None = None, at: datetime | None = None
) -> AttendanceEntry:
    """Clock an employee in, creating an open attendance entry.

    ``employee_id`` defaults to the caller's own employee record.
    Clocking in on someone else's behalf requires admin/manager (a
    manager only within their own departments). ``at`` defaults to now;
    only admin/manager may override it (source becomes ``'manual'``) —
    an employee can never backdate their own clock-in.
    """
    target_employee_id = employee_id if employee_id is not None else scope.employee_id
    if target_employee_id is None:
        raise ValidationError("No employee specified for clock-in.")

    acting_for_self = target_employee_id == scope.employee_id
    if not acting_for_self and scope.role not in ("admin", "manager"):
        abort(403)

    _validate_employee_for_scope(scope, target_employee_id)

    if at is not None and scope.role not in ("admin", "manager"):
        raise ValidationError("Only an admin or manager may set a custom clock-in time.")

    tz = organization_timezone(scope)
    started_at = _localize(at, tz) if at is not None else datetime.now(timezone.utc)
    _validate_started_at_window(started_at)
    source = "manual" if (at is not None or not acting_for_self) else "web"

    entry = AttendanceEntry(
        organization_id=scope.organization_id,
        employee_id=target_employee_id,
        shift_id=_match_shift(scope.organization_id, target_employee_id, started_at),
        started_at=started_at,
        business_date=business_date_for(started_at, tz),
        break_minutes=0,
        status="open",
        source=source,
        created_by_user_id=scope.user_id,
    )
    db.session.add(entry)
    _commit_or_raise()
    return entry


def clock_out(
    scope: AccessScope, attendance_entry_id: int, at: datetime | None = None
) -> AttendanceEntry:
    """Clock out an open attendance entry.

    The entry's own employee, or admin/manager (manager only within their
    department), may close it. ``at`` defaults to now; only admin/manager
    may override it, same restriction as ``clock_in`` (see module
    docstring). Rejects an entry that's already closed.

    Round B fix: a ``needs_review`` entry (auto-flagged by
    ``flag_stale_open_entries`` after being open too long with no
    clock-out) can no longer be resolved by a plain clock-out at all —
    that defeats the purpose of the review flag, most obviously when the
    entry's own employee closes it with no admin involvement and no cap
    on the resulting duration. Only ``correct_entry`` (admin/manager,
    mandatory ``edit_reason``) may resolve one.
    """
    entry = _get_entry_for_scope(scope, attendance_entry_id)

    if entry.status == "closed":
        raise ValidationError("This attendance entry is already closed.")

    if entry.status == "needs_review":
        raise ValidationError(
            "This entry was flagged for review after being open too long; "
            "only a correction (with a reason) can resolve it."
        )

    if at is not None and scope.role not in ("admin", "manager"):
        raise ValidationError("Only an admin or manager may set a custom clock-out time.")

    tz = organization_timezone(scope)
    ended_at = _localize(at, tz) if at is not None else datetime.now(timezone.utc)
    _validate_ended_at_not_in_future(ended_at)
    _validate_ended_after_started(entry.started_at, ended_at)

    entry.ended_at = ended_at
    entry.status = "closed"
    _commit_or_raise()
    return entry


def correct_entry(
    scope: AccessScope,
    attendance_entry_id: int,
    edit_reason: str,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    break_minutes: int | None = None,
) -> AttendanceEntry:
    """Correct an attendance entry's recorded times. Admin/manager only.

    This is the only way an entry's times may change after creation — no
    generic ``update_entry``. ``edit_reason`` is mandatory and is always
    stored together with ``edited_by_user_id``/``edited_at`` in the same
    write, so the DB's
    ``edited_by_user_id IS NULL OR (edited_at IS NOT NULL AND edit_reason
    IS NOT NULL)`` CHECK is satisfied by construction. Never callable by
    the employee themselves, even for their own record.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

    if not edit_reason or not edit_reason.strip():
        raise ValidationError(
            "A reason is required to correct an attendance entry.",
            field="edit_reason",
        )

    entry = _get_entry_for_scope(scope, attendance_entry_id)
    tz = organization_timezone(scope)

    if started_at is not None:
        localized_started_at = _localize(started_at, tz)
        _validate_started_at_window(localized_started_at)
        entry.started_at = localized_started_at
        entry.business_date = business_date_for(entry.started_at, tz)
    if ended_at is not None:
        localized_ended_at = _localize(ended_at, tz)
        _validate_ended_at_not_in_future(localized_ended_at)
        entry.ended_at = localized_ended_at
        entry.status = "closed"
    if entry.ended_at is not None:
        _validate_ended_after_started(entry.started_at, entry.ended_at)
    if started_at is not None:
        # Re-run shift-matching against the corrected time — otherwise
        # the entry keeps pointing at whichever shift (if any) it
        # originally matched, which reports.attendance_entries_with_
        # context then computes lateness against, producing nonsense
        # (or silently wrong) minutes-late figures once the entry no
        # longer actually falls near that shift's window. Deliberately
        # done only after both started_at and ended_at (if given) are
        # already set on ``entry``: this query's autoflush would
        # otherwise persist started_at alone, transiently violating the
        # DB's 24-hour duration CHECK against the *old* ended_at whenever
        # a correction moves both times together.
        entry.shift_id = _match_shift(
            scope.organization_id, entry.employee_id, entry.started_at
        )
    if break_minutes is not None:
        entry.break_minutes = break_minutes

    entry.edited_by_user_id = scope.user_id
    entry.edited_at = datetime.now(timezone.utc)
    entry.edit_reason = edit_reason.strip()

    _flush_or_raise()
    # changes excludes edit_reason: it's free-text an admin/manager
    # writes and may contain a personal/medical circumstance (e.g. "left
    # early for a doctor's appointment"), the same privacy reasoning
    # app.services.leave.approve_leave/reject_leave already apply to
    # decision_note.
    audit_service.record(
        "attendance_corrected",
        "attendance_entry",
        entity_id=entry.id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={"employee_id": entry.employee_id},
    )
    # One commit covers both the correction and the audit entry above —
    # see app.services.audit's module docstring.
    db.session.commit()
    return entry


def flag_stale_open_entries(cutoff_hours: int = 16) -> int:
    """Mark every open entry with no clock-out after ``cutoff_hours`` as
    ``needs_review`` (confirmed rule A11).

    Never invents an end time — only the status changes. Organization-
    wide (no ``AccessScope``): this is a maintenance operation meant to
    run periodically for the whole system (see ``flask attendance
    flag-stale``), not a user-facing, per-tenant action.

    Returns the number of entries flagged.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    stale_entries = (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.status == "open",
            AttendanceEntry.started_at <= cutoff,
        )
        .all()
    )
    for entry in stale_entries:
        entry.status = "needs_review"
    db.session.commit()
    return len(stale_entries)


def get_open_entry(scope: AccessScope) -> AttendanceEntry | None:
    """The caller's own currently-unresolved (``ended_at IS NULL``)
    attendance entry, if any — covers both ``open`` and ``needs_review``
    states, since both leave ``ended_at`` unset.

    Deliberately unbounded by date rather than a recent-days window: an
    entry with no clock-out has no upper bound on how long it can stay
    that way (only a *closed* entry's duration is capped at 24 hours —
    see migration 0014 — an open one is not), so a fixed lookback window
    can miss a genuinely still-open or still-flagged entry and leave the
    caller wrongly shown as "not clocked in" with no way to actually
    clock in (blocked by the open-entry unique index) or resolve the
    flag themselves. The DB's own
    ``uq_attendance_entries_employee_id_open`` partial index guarantees
    at most one such row per employee, so this is always a cheap,
    single-row lookup, never a scan.
    """
    if scope.employee_id is None:
        return None
    return (
        db.session.query(AttendanceEntry)
        .filter(
            AttendanceEntry.organization_id == scope.organization_id,
            AttendanceEntry.employee_id == scope.employee_id,
            AttendanceEntry.ended_at.is_(None),
        )
        .first()
    )


def list_entries(
    scope: AccessScope, start, end, employee_id: int | None = None
) -> list[AttendanceEntry]:
    """List attendance entries visible to ``scope`` with ``business_date``
    in [start, end]. Scoped the same way as ``scheduling.list_shifts``:
    admin sees the whole organization, a manager only their departments
    (via a join to the owning employee, since entries have no
    ``department_id`` of their own), and an employee only their own
    entries.
    """
    if scope.role == "employee":
        if scope.employee_id is None:
            return []
        query = db.session.query(AttendanceEntry).filter(
            AttendanceEntry.organization_id == scope.organization_id,
            AttendanceEntry.employee_id == scope.employee_id,
            AttendanceEntry.business_date >= start,
            AttendanceEntry.business_date <= end,
        )
        return query.order_by(AttendanceEntry.started_at).all()

    query = db.session.query(AttendanceEntry).filter(
        AttendanceEntry.organization_id == scope.organization_id,
        AttendanceEntry.business_date >= start,
        AttendanceEntry.business_date <= end,
    )
    if scope.role == "manager":
        query = query.join(Employee, Employee.id == AttendanceEntry.employee_id).filter(
            Employee.department_id.in_(scope.department_ids)
        )
    if employee_id is not None:
        query = query.filter(AttendanceEntry.employee_id == employee_id)
    return query.order_by(AttendanceEntry.started_at).all()
