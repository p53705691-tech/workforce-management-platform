"""Reports service: read-only composition over already-verified services.

Per this milestone's confirmed constraint (see the M8 plan and
CLAUDE.md's Source of Truth section): every number here comes from an
existing, already-tested service function
(``scheduling``/``attendance``/``working_hours``/``leave``/``labor_cost``/
``overtime``). Nothing in this module invents a new hours formula, a new
cost formula, or a new overtime rule — it only aggregates or filters data
those modules already compute correctly.

Every function takes the caller's ``AccessScope`` and enforces
authorization itself, same pattern as every other service module in this
project.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from flask import abort

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.department import Department
from app.models.shift import Shift
from app.models.user import User
from app.services import attendance as attendance_service
from app.services import audit as audit_service
from app.services import employees as employee_service
from app.services import labor_cost as labor_cost_service
from app.services import leave as leave_service
from app.services import scheduling as scheduling_service
from app.services import working_hours as working_hours_service
from app.services.errors import ValidationError

_SECONDS_PER_HOUR = Decimal(3600)


def today_business_date(scope: AccessScope) -> date:
    """"Today", attributed per rule A1 (the organization's local date),
    reused by every "as of today" report below instead of each one
    recomputing it — see ``scheduling.business_date_for``.
    """
    tz = scheduling_service.organization_timezone(scope)
    return scheduling_service.business_date_for(datetime.now(timezone.utc), tz)


def _published_shifts_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Published shifts whose ``business_date`` is today, scoped to
    ``scope`` (and further to ``department_id`` if given), with no
    time-of-day filtering — the shared base list both
    ``who_is_working_today`` and ``who_is_absent_today`` narrow further,
    each against a different point of ``shift.starts_at``/``ends_at``
    versus "now" (see each function's own docstring for why the two
    windows differ).
    """
    today = today_business_date(scope)
    shifts = scheduling_service.list_shifts(scope, today, today, department_id=department_id)
    return [shift for shift in shifts if shift.status == "published"]


def who_is_working_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Published shifts today that are currently in progress (``starts_at
    <= now <= ends_at``), scoped to ``scope`` (and further to
    ``department_id`` if given).

    Before this filter, any published shift for today counted as
    "working" regardless of the time of day — a shift starting 8 hours
    from now, or one that ended 14 hours ago, both showed up as
    currently "Working" on the dashboard. This is a schedule-based
    signal only (no attendance is consulted): it answers "whose shift
    covers this instant", not "who has actually clocked in".
    """
    now = datetime.now(timezone.utc)
    return [
        shift
        for shift in _published_shifts_today(scope, department_id=department_id)
        if shift.starts_at <= now <= shift.ends_at
    ]


def who_is_on_leave_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Approved leave requests whose range covers today, scoped to
    ``scope`` (and further to ``department_id`` if given).

    Composed from ``leave.list_leave_requests`` — the "does this range
    cover today" comparison is pushed into the query itself via the
    ``covers`` parameter (Round B fix: this used to load every approved
    request the organization has ever had and filter in Python, an
    unbounded query that only grows with history) rather than an invented
    business rule of its own.
    """
    today = today_business_date(scope)
    tz = scheduling_service.organization_timezone(scope)
    day_start = datetime.combine(today, time.min, tzinfo=tz)
    day_end = datetime.combine(today, time.max, tzinfo=tz)

    covering_today = leave_service.list_leave_requests(
        scope, status="approved", covers=(day_start, day_end)
    )

    if department_id is None:
        return covering_today

    department_employee_ids = {
        employee.id
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department_id
    }
    return [
        leave_request
        for leave_request in covering_today
        if leave_request.employee_id in department_employee_ids
    ]


def who_is_absent_today(scope: AccessScope, department_id: int | None = None) -> list:
    """Employees whose published shift today has already started, with no
    attendance entry at all for today, and not on approved leave covering
    today (an employee on leave is a different classification, not
    "absent").

    Composed entirely from ``_published_shifts_today`` (this module),
    ``attendance.list_entries`` and ``who_is_on_leave_today``.

    Deliberately not built from ``who_is_working_today``: that function
    now requires a shift to still be *in progress* (``starts_at <= now
    <= ends_at``), which would make a no-show stop counting as absent the
    moment their shift's scheduled end time passes — clearly wrong, an
    employee who never showed up stays absent for the rest of the day.
    The two functions instead share only the unfiltered
    ``_published_shifts_today`` base and each apply their own,
    independent time-of-day condition, which is also what keeps them
    disjoint before a shift starts: an employee cannot be "absent" from a
    shift that has not started yet (Round C fix — this previously flagged
    every not-yet-started employee as absent, identical to that same
    employee's shift also making them "working" on the same dashboard).

    Round B fix: this used to require the attendance entry's ``shift_id``
    to match the specific shift being checked. But
    ``attendance._match_shift`` deliberately leaves ``shift_id`` NULL
    whenever zero or *more than one* published shift falls within the
    clock-in grace window — that's "I could not decide which shift this
    belongs to", not "this employee did not work". An employee who clocks
    in early enough to miss the grace window, or who has two shifts the
    same day, was incorrectly reported absent despite being clocked in.
    Presence is now "does this employee have any attendance entry today
    at all", independent of which (if any) shift it links to.
    """
    now = datetime.now(timezone.utc)
    shifts_today = [
        shift
        for shift in _published_shifts_today(scope, department_id=department_id)
        if shift.starts_at <= now
    ]
    if not shifts_today:
        return []

    today = today_business_date(scope)
    entries_today = attendance_service.list_entries(scope, today, today)
    present_employee_ids = {entry.employee_id for entry in entries_today}
    on_leave_employee_ids = {
        leave_request.employee_id
        for leave_request in who_is_on_leave_today(scope, department_id=department_id)
    }
    employees_by_id = {
        employee.id: employee for employee in employee_service.list_employees(scope)
    }

    absent = []
    seen_employee_ids = set()
    for shift in shifts_today:
        if shift.employee_id in present_employee_ids:
            continue
        if shift.employee_id in on_leave_employee_ids:
            continue
        if shift.employee_id in seen_employee_ids:
            continue
        employee = employees_by_id.get(shift.employee_id)
        if employee is None:
            continue
        seen_employee_ids.add(shift.employee_id)
        absent.append(employee)
    return absent


def current_attendance_status(scope: AccessScope) -> dict | None:
    """The caller's own currently-open or needs-review (not yet resolved)
    attendance entry, if any, plus how long it has been open — for a
    "Currently Working" / "Needs Review" dashboard display only.

    Deliberately NOT worked hours: ``working_hours.worked_seconds_for_day``
    /``_for_week`` only ever count *closed* entries (an open entry's
    duration is provisional until clock-out — it could still be corrected
    or is simply not over yet), so this elapsed figure must never be
    labeled or summed as authoritative worked time anywhere it's
    rendered. It exists purely to answer "am I clocked in, and since
    when" — the same two facts the underlying row already carries.

    Uses ``attendance.get_open_entry`` (unbounded by date — see that
    function's docstring for why a recent-days window previously used
    here could miss an old, still-unresolved entry and wrongly show the
    caller as "not clocked in").
    """
    open_entry = attendance_service.get_open_entry(scope)
    if open_entry is None:
        return None

    elapsed_seconds = int((datetime.now(timezone.utc) - open_entry.started_at).total_seconds())
    return {
        "entry": open_entry,
        "elapsed_hours": elapsed_seconds // 3600,
        "elapsed_minutes": (elapsed_seconds % 3600) // 60,
    }


# How far back to scan for still-open ``needs_review`` attendance entries
# (see ``attendance.flag_stale_open_entries``). Needs_review is a status,
# not a "today" event — an entry flagged stale yesterday morning is still
# exactly as actionable today. Bounded rather than unbounded so this can
# never become a full-table scan; 7 days (matching this module's existing
# cost-window convention) is generous for something meant to be corrected
# promptly, not a long-lived backlog.
_ATTENTION_LOOKBACK_DAYS = 6


def attendance_needing_review(scope: AccessScope, department_id: int | None = None) -> list:
    """Attendance entries currently flagged ``needs_review`` — i.e. a
    clock-in with no clock-out that ``attendance.flag_stale_open_entries``
    has already marked stale — within a bounded lookback window.

    A thin filter over ``attendance.list_entries``, the same read path
    the Attendance page itself uses; no attendance business logic here,
    only a read composition (this module invents no new status or rule).
    """
    today = today_business_date(scope)
    start = today - timedelta(days=_ATTENTION_LOOKBACK_DAYS)
    entries = attendance_service.list_entries(scope, start, today)
    entries = [entry for entry in entries if entry.status == "needs_review"]

    if department_id is None:
        return entries

    department_employee_ids = {
        employee.id
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department_id
    }
    return [entry for entry in entries if entry.employee_id in department_employee_ids]


def recent_activity(scope: AccessScope, start: date, end: date, limit: int = 5) -> list[dict]:
    """The most recent audit-log entries for the caller's organization,
    with each entry's actor email resolved for display.

    Admin only — enforced here independently of the route, same
    belt-and-suspenders pattern ``audit.list_entries`` (which this calls)
    already uses. The audit log itself has no name/email on an entry, only
    ``actor_user_id``, so the small set of actor ids for this page's
    entries is resolved in one batched query rather than one per row.
    """
    if scope.role != "admin":
        abort(403)

    page = audit_service.list_entries(scope, start, end, page=1, page_size=limit)

    actor_ids = {entry.actor_user_id for entry in page.entries if entry.actor_user_id is not None}
    actor_emails = {}
    if actor_ids:
        actor_emails = {
            user.id: user.email
            for user in db.session.query(User)
            .filter(User.id.in_(actor_ids), User.organization_id == scope.organization_id)
            .all()
        }

    return [
        {"entry": entry, "actor_email": actor_emails.get(entry.actor_user_id)}
        for entry in page.entries
    ]


def attendance_entries_with_context(
    scope: AccessScope, start: date, end: date, employee_id: int | None = None
) -> list[dict]:
    """Attendance entries for [start, end], enriched with two derived,
    display-only fields the Attendance page needs: worked duration for
    closed entries, and lateness against whichever shift the entry
    matched (if any).

    Thin composition over ``attendance.list_entries`` — the duration
    arithmetic mirrors ``working_hours._worked_seconds`` exactly (ended -
    started - break), applied per entry instead of summed per day; no
    new hours formula. Lateness only exists when the entry already
    matched a shift at clock-in time (``attendance._match_shift``,
    stored as ``AttendanceEntry.shift_id``) — an unscheduled entry has
    nothing to be late against, so it gets no lateness figure at all
    rather than a misleading zero. Shifts are batch-loaded once instead
    of one query per entry.
    """
    entries = attendance_service.list_entries(scope, start, end, employee_id=employee_id)

    shift_ids = {entry.shift_id for entry in entries if entry.shift_id is not None}
    shifts_by_id = {}
    if shift_ids:
        shifts_by_id = {
            shift.id: shift
            for shift in db.session.query(Shift)
            .filter(Shift.id.in_(shift_ids), Shift.organization_id == scope.organization_id)
            .all()
        }

    context = []
    for entry in entries:
        worked_hours = None
        if entry.status == "closed":
            duration_seconds = int((entry.ended_at - entry.started_at).total_seconds())
            duration_seconds -= entry.break_minutes * 60
            worked_hours = Decimal(duration_seconds) / _SECONDS_PER_HOUR

        shift = shifts_by_id.get(entry.shift_id) if entry.shift_id is not None else None
        late_minutes = None
        if shift is not None and entry.started_at > shift.starts_at:
            late_minutes = int((entry.started_at - shift.starts_at).total_seconds()) // 60

        context.append(
            {
                "entry": entry,
                "worked_hours": worked_hours,
                "shift": shift,
                "late_minutes": late_minutes,
            }
        )
    return context


def _department_employees(scope: AccessScope, department_id: int) -> list:
    """Employees of ``department_id``, after confirming the caller may
    report on it (same manager/department and existence checks as
    ``labor_cost.department_cost_summary``).
    """
    if scope.role == "manager" and department_id not in scope.department_ids:
        abort(404)

    department = (
        db.session.query(Department)
        .filter(
            Department.id == department_id,
            Department.organization_id == scope.organization_id,
        )
        .first()
    )
    if department is None:
        abort(404)

    return [
        employee
        for employee in employee_service.list_employees(scope)
        if employee.department_id == department_id
    ]


def _date_range(start_date: date, end_date: date) -> list[date]:
    span = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(span + 1)]


def my_overtime_hours(scope: AccessScope, start_date: date, end_date: date) -> Decimal | None:
    """The caller's own overtime hours for a date range — self-service
    equivalent of ``overtime_summary``, same safe-reading pattern: reuses
    ``labor_cost.range_cost_for_employee`` and reads only ``.hours``/
    ``.category``, never ``.rate``/``.cost``. Labor cost is a managerial
    concern (rule A4); overtime *hours* about one's own time are not.

    Returns ``None`` (rather than raising) when the caller has no pay
    rate or overtime policy configured for the range, since this is a
    "my hours" page, not a cost report — the page can show "not
    available" for this one figure without failing the whole page, the
    same isolation ``overtime_summary`` already applies per employee.
    """
    if scope.employee_id is None:
        return None
    try:
        line_items = labor_cost_service.range_cost_for_employee(
            scope, scope.employee_id, start_date, end_date
        )
    except ValidationError:
        return None
    return sum(
        (item.hours for item in line_items if item.category != "regular"), Decimal("0")
    )


def overtime_summary(
    scope: AccessScope, department_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Per-employee total overtime hours (daily + weekly OT combined) for
    a department over a date range.

    Reuses ``labor_cost.range_cost_for_employee``'s already-correct daily
    and weekly overtime tiering and reclassification (so a hand-rolled
    version here could never accidentally double-count an hour under two
    multipliers) rather than re-deriving it. Only ``LineItem.hours`` and
    ``.category`` are ever read — never ``.rate`` or ``.cost`` — so this
    can never surface a pay rate or a per-employee cost figure (rule A4),
    even though the underlying line items technically carry one.

    Ambiguity resolved here: reusing ``range_cost_for_employee`` means an
    employee with no pay rate or overtime policy configured for the range
    raises the same ``ValidationError`` labor cost reporting already
    raises for that gap. Since this is an hours report, not a money one,
    failing the entire report for every other employee over one missing
    rate would be worse than the alternative: that employee is returned
    with ``"configured": False`` and no hours figure, and the route
    surfaces this as a per-row note instead of failing the page.

    Fetches every employee's line items in one batched call
    (``labor_cost.range_cost_for_employees``) instead of looping
    ``range_cost_for_employee`` once per employee — the N+1 pattern this
    replaced (three queries per employee, fanning out across an entire
    department). See that function's docstring for how it guarantees the
    same per-employee numbers as the old per-employee loop.

    ``range_cost_for_employees`` raises ``ValidationError`` once, up
    front, for an invalid range (``end_date < start_date``) rather than
    per employee — unlike the per-employee configuration gap above, a
    reversed range isn't a fact about any one employee. The old
    per-employee loop happened to raise (and catch) that same error once
    per employee, so every row came back ``"configured": False`` for a
    reversed range; that observable behavior — every employee
    unconfigured, no exception reaching the route — is preserved
    explicitly here, since ``overtime_report`` (``app.routes.dashboard``)
    already has its own dedicated "Invalid date range" UI state that
    takes precedence over this summary's content and does not expect
    this function to raise.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

    employees = _department_employees(scope, department_id)
    employee_ids = [employee.id for employee in employees]
    try:
        line_items_by_employee = labor_cost_service.range_cost_for_employees(
            scope, employee_ids, start_date, end_date
        )
    except ValidationError:
        line_items_by_employee = {employee_id: None for employee_id in employee_ids}

    summary = []
    for employee in employees:
        line_items = line_items_by_employee.get(employee.id)
        if line_items is None:
            summary.append({"employee": employee, "ot_hours": None, "configured": False})
            continue

        ot_hours = sum(
            (item.hours for item in line_items if item.category != "regular"),
            Decimal("0"),
        )
        summary.append({"employee": employee, "ot_hours": ot_hours, "configured": True})
    return summary


def hours_trend(
    scope: AccessScope, department_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Per-day total worked hours for a department across a date range —
    a minimal aggregation answering "how are working hours changing over
    time", composed from ``working_hours.worked_seconds_by_range_for_employees``
    (one query for every employee in the department across the whole
    range, not one query per employee — see that function's docstring
    for the N+1 pattern this replaced, measured at a ~2.2s admin
    dashboard load with just 12 employees / 4 departments before the
    original per-day version of this fix). No new hours formula.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)

    employees = _department_employees(scope, department_id)
    employee_ids = [employee.id for employee in employees]

    seconds_by_employee = working_hours_service.worked_seconds_by_range_for_employees(
        scope, employee_ids, start_date, end_date
    )

    seconds_by_date: dict[date, int] = {}
    for employee_seconds_by_date in seconds_by_employee.values():
        for business_date, seconds in employee_seconds_by_date.items():
            seconds_by_date[business_date] = seconds_by_date.get(business_date, 0) + seconds

    return [
        {
            "date": business_date,
            "total_hours": Decimal(seconds_by_date.get(business_date, 0)) / _SECONDS_PER_HOUR,
        }
        for business_date in _date_range(start_date, end_date)
    ]
