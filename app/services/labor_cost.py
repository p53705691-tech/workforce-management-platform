"""Labor cost service: combines working hours, overtime tiering, and pay
rates into Decimal money figures.

This module is the money layer on top of three already-verified
building blocks — ``app.services.working_hours`` (worked seconds),
``app.services.overtime`` (pure tiering math) and ``app.services.pay_rates``
(effective-dated Decimal rates) — and deliberately adds no new business
rule to any of them; it only prices what they already compute.

Money rounding (confirmed rule A12): one ``LineItem`` per (employee,
business_date, pay-rate category — regular / a specific daily-OT tier /
a specific weekly-OT tier), each independently rounded to 2dp with
``ROUND_HALF_UP``. Totals are always the sum of already-rounded line
items, never a rounding of a combined raw total — see
``test_labor_cost.py``'s dedicated rounding-divergence test for a case
where the two approaches disagree by a cent, proving this is actually
what happens here.

Ambiguity resolved during implementation — weekly overtime vs. the daily
"regular" bucket: ``overtime.compute_weekly_overtime`` returns hours that
exceed the weekly threshold, computed from the *regular* (non-daily-OT)
hours pool across a week. Its own docstring already establishes that a
worked hour must never be paid under two multipliers at once. Naively
adding a weekly-OT ``LineItem`` on top of the untouched daily "regular"
line items would do exactly that — the same hour would be paid once at
1x (daily regular) and again at the weekly multiplier (e.g. 1.5x),
silently overpaying, which CLAUDE.md forbids outright. So
``range_cost_for_employee`` reclassifies weekly-OT-eligible hours *out
of* the regular pool before building the daily "regular" line items,
walking backward from the end of the week (the hours that pushed the
week over its threshold are, by convention, the ones worked latest in
the week) so every worked hour ends up priced in exactly one line item.
Each reclassified hour's weekly-OT ``LineItem`` is priced at the rate in
force on the specific day it was reclassified *from* — if an hourly rate
changes in the middle of the days being reclassified, different portions
of the same weekly-OT tier can legitimately be priced at different
rates. Hourly-rate changes mid-week are expected to be rare, but this
follows directly from attributing hours to the day they actually came
from (see the proration note below) rather than a single date.

Round A fix (partial-week proration, chosen over rejecting misaligned
ranges): earlier versions of this function reclassified hours out of the
regular pool for *any* day in the touched week — including days outside
``[start_date, end_date]`` whose own line item is never emitted — and
then emitted a single weekly-OT ``LineItem`` for the whole week's
reclassified hours, lumped onto ``min(week_end, end_date)`` regardless of
which days actually contributed those hours. That meant a request for a
single day within a heavy week could return a non-zero weekly-OT charge
priced from hours worked on a day never requested, and two adjacent
requests that together span a full week would each independently bill
the *full* week's weekly-OT hours (double-counting).

Fixed by **prorating** (option (a)): the reclassification now tracks
exactly which day (and which tier) each reclassified hour came from, and
a weekly-OT ``LineItem`` is only emitted for the portion of reclassified
hours whose source day actually falls inside ``[start_date, end_date]``,
attributed to that specific day rather than a single end-of-week date.
This was chosen over rejecting misaligned ranges (option (b)) because
both ``department_cost_summary`` and every route that calls
``range_cost_for_employee``/``department_cost_summary``
(``app.routes.labor_cost``, ``app.routes.dashboard``) already accept and
rely on arbitrary caller-supplied ``start``/``end`` query parameters with
no week-alignment assumption; rejecting misaligned ranges would have
required snapping every default window (and erroring on most ad hoc
user-supplied ranges) to a policy's ``week_start_day``, which is itself
configurable per organization and can change over time — a much more
invasive, user-visible change for what is fundamentally a pricing-detail
bug. With proration, ``cost(mon..sun) == cost(mon..wed) + cost(thu..sun)``
for any adjacent split of a week (see
``test_labor_cost_service.py``'s dedicated invariant test).

Known, deliberate MVP scope limitation — paid leave is not costed:
labor cost is derived solely from closed ``AttendanceEntry`` rows.
``LeaveType.is_paid`` is stored on the schema but never read here or
anywhere else in this module; approved leave (paid or not) currently
contributes exactly zero to every labor-cost figure in this system. This
is stated explicitly here — per CLAUDE.md's "state the ambiguity instead
of inventing behavior" rule — rather than left as a silent gap, because
implementing paid-leave costing is a real business-rule decision this
module isn't authorized to make on its own: it requires deciding how
leave hours interact with the daily/weekly overtime thresholds (does
paid leave count toward "hours worked" for OT purposes? almost
certainly not, but that has never been confirmed) and what rate a leave
hour is priced at. Treat this as an open follow-up, not an oversight.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import abort

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.department import Department
from app.models.employee import Employee
from app.services import overtime as overtime_service
from app.services import pay_rates as pay_rate_service
from app.services import working_hours as working_hours_service
from app.services.errors import ValidationError

_SECONDS_PER_HOUR = Decimal(3600)
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class DepartmentCostSummary:
    """Aggregate labor cost for a department over a date range, with
    per-employee configuration gaps isolated rather than blanking the
    whole result (Round A fix — mirrors
    ``reports.overtime_summary``'s existing per-employee
    error-isolation pattern). ``total`` only ever covers the employees
    who *are* fully configured for the range; ``unconfigured_employee_count``
    says how many were excluded so the caller can surface that instead
    of a bare, unexplained total.
    """

    total: Decimal
    unconfigured_employee_count: int


@dataclass(frozen=True)
class LineItem:
    """One priced slice of a single employee's single day, at a single
    multiplier. ``category`` traces back to exactly which bucket produced
    it: ``"regular"``, ``"daily_ot_<tier index>"`` (1-based, in tier
    order), or ``"weekly_ot_<tier index>"``.
    """

    employee_id: int
    business_date: date
    category: str
    hours: Decimal
    rate: Decimal
    multiplier: Decimal
    cost: Decimal


def _rounded_cost(hours: Decimal, rate: Decimal, multiplier: Decimal) -> Decimal:
    """Round one line item's cost to 2dp using ROUND_HALF_UP (confirmed
    rule A12) — the actual crux of this milestone: cost is rounded per
    line item, never derived from a rounded total.
    """
    return (hours * rate * multiplier).quantize(_CENT, rounding=ROUND_HALF_UP)


def _make_line_item(
    employee_id: int,
    business_date: date,
    category: str,
    hours: Decimal,
    rate: Decimal,
    multiplier: Decimal,
) -> LineItem:
    return LineItem(
        employee_id=employee_id,
        business_date=business_date,
        category=category,
        hours=hours,
        rate=rate,
        multiplier=multiplier,
        cost=_rounded_cost(hours, rate, multiplier),
    )


def _daily_breakdown(scope: AccessScope, employee_id: int, business_date: date):
    """(rate, resolved_policy, regular_hours, daily_ot_buckets) for one
    employee on one day.

    Raises ``ValidationError`` naming what's missing if no pay rate or no
    overtime policy is configured for ``business_date`` — never silently
    assumes a rate of zero or skips overtime (confirmed rule for this
    milestone: that would silently produce wrong money).

    Round A fix: this no longer holds for a day with zero hours worked.
    ``range_cost_for_employee`` must expand to every day of a touched
    week to compute weekly OT correctly, which previously meant a new
    hire (pay rate ``effective_from`` after the week's Monday) or a
    terminated employee (pay rate ``effective_to`` before the week's
    Sunday) made the *entire* week's calculation raise, even though the
    days actually missing configuration had nothing to price. A missing
    rate/policy only matters when there are hours to price; a zero-hour
    day outside an employee's employment window (or before overtime
    tracking existed) is not a configuration gap worth failing on.
    ``rate``/``policy`` may come back ``None`` in that case — callers
    must not price line items from them, which is automatically true
    here since ``regular_hours`` is ``0`` and ``ot_buckets`` is empty.
    """
    worked_seconds = working_hours_service.worked_seconds_for_day(
        scope, employee_id, business_date
    )
    worked_hours = Decimal(worked_seconds) / _SECONDS_PER_HOUR

    rate = pay_rate_service.resolve_pay_rate(
        employee_id, scope.organization_id, business_date
    )
    policy = overtime_service.resolve_policy(scope.organization_id, business_date)

    if worked_hours == 0:
        return rate, policy, Decimal("0"), []

    if rate is None:
        raise ValidationError(
            f"No pay rate configured for employee {employee_id} on "
            f"{business_date.isoformat()}."
        )
    if policy is None:
        raise ValidationError(
            f"No overtime policy configured for {business_date.isoformat()}."
        )

    regular_hours, ot_buckets = overtime_service.compute_daily_overtime(
        worked_hours, policy.daily_threshold_hours, policy.daily_tiers
    )
    return rate, policy, regular_hours, ot_buckets


def _daily_line_items(
    employee_id: int,
    business_date: date,
    rate: Decimal,
    regular_hours: Decimal,
    ot_buckets,
) -> list[LineItem]:
    line_items = []
    if regular_hours > 0:
        line_items.append(
            _make_line_item(
                employee_id, business_date, "regular", regular_hours, rate, Decimal("1")
            )
        )
    for index, bucket in enumerate(ot_buckets, start=1):
        line_items.append(
            _make_line_item(
                employee_id,
                business_date,
                f"daily_ot_{index}",
                bucket.hours,
                rate,
                bucket.multiplier,
            )
        )
    return line_items


def daily_cost_for_employee(
    scope: AccessScope, employee_id: int, business_date: date
) -> list[LineItem]:
    """One ``LineItem`` per pay-rate bucket (regular + each daily-OT
    tier reached) for one employee on one day.
    """
    rate, _policy, regular_hours, ot_buckets = _daily_breakdown(
        scope, employee_id, business_date
    )
    return _daily_line_items(employee_id, business_date, rate, regular_hours, ot_buckets)


def _date_range(start_date: date, end_date: date) -> list[date]:
    span = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(span + 1)]


def _week_start(business_date: date, week_start_day: int) -> date:
    offset = (business_date.weekday() - week_start_day) % 7
    return business_date - timedelta(days=offset)


def range_cost_for_employee(
    scope: AccessScope, employee_id: int, start_date: date, end_date: date
) -> list[LineItem]:
    """One ``LineItem`` per pay-rate bucket for every day in
    ``[start_date, end_date]``, plus a weekly-OT ``LineItem`` per tier
    for each week the range touches.

    Correctly computing weekly overtime for a given week requires that
    week's *entire* 7-day regular-hours total (per M5), not just
    whichever days happen to fall inside the requested range — so a
    week only partially covered by ``[start_date, end_date]`` still has
    its other days' pay rate and overtime policy resolved internally
    (raising ``ValidationError`` if either is missing for one of those
    days too, even though no ``LineItem`` for that day is ever returned).
    See the module docstring for how weekly-OT hours are reclassified out
    of the daily "regular" bucket to avoid double-paying the same hour,
    and for why the resulting weekly-OT ``LineItem``\\ s are prorated to
    only the portion of reclassified hours whose source day actually
    falls inside ``[start_date, end_date]``.
    """
    if end_date < start_date:
        raise ValidationError("end_date must be on or after start_date.")

    breakdown_cache: dict[date, tuple] = {}

    def get_breakdown(business_date: date):
        if business_date not in breakdown_cache:
            breakdown_cache[business_date] = _daily_breakdown(
                scope, employee_id, business_date
            )
        return breakdown_cache[business_date]

    requested_dates = _date_range(start_date, end_date)
    for business_date in requested_dates:
        get_breakdown(business_date)

    # regular_hours_after_weekly starts as each requested day's raw
    # regular hours; a week's worth of weekly-OT reclassification (below)
    # may reduce specific days' entries before the "regular" line items
    # are actually built.
    regular_hours_after_weekly = {
        business_date: get_breakdown(business_date)[2] for business_date in requested_dates
    }

    # A requested date's policy can be None if that day has zero worked
    # hours and no overtime policy resolves for it (e.g. before overtime
    # tracking existed for the org) — see _daily_breakdown. Such a date
    # can't be placed into a week for weekly-OT purposes, but since it
    # has no hours to price, it also can't itself need weekly-OT
    # reclassification, so it's safe to leave it out of this set; any
    # other requested date that shares its real week and does carry
    # hours will already have a resolvable policy (a worked day with a
    # missing policy raises in _daily_breakdown) and will seed that
    # week's expansion on its own.
    week_starts = {
        _week_start(business_date, get_breakdown(business_date)[1].week_start_day)
        for business_date in requested_dates
        if get_breakdown(business_date)[1] is not None
    }

    weekly_line_items: list[LineItem] = []

    for week_start in sorted(week_starts):
        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        for business_date in week_dates:
            get_breakdown(business_date)

        daily_results = []
        for business_date in week_dates:
            _rate, _policy, regular_hours, ot_buckets = get_breakdown(business_date)
            daily_ot_hours = sum((bucket.hours for bucket in ot_buckets), Decimal("0"))
            daily_results.append((business_date, regular_hours, daily_ot_hours))

        # week_start itself may be a zero-hour day with no resolvable
        # policy (e.g. before the employee's employment window began),
        # so any day in the week with a resolved policy stands in for
        # it instead. If literally no day in the week has a resolvable
        # policy, every day in it necessarily has zero worked hours too
        # (a worked day with no policy already raised in
        # _daily_breakdown above), so there is nothing to reclassify.
        weekly_policy = next(
            (
                get_breakdown(business_date)[1]
                for business_date in week_dates
                if get_breakdown(business_date)[1] is not None
            ),
            None,
        )
        if weekly_policy is None:
            continue
        weekly_buckets = overtime_service.compute_weekly_overtime(
            daily_results, weekly_policy.weekly_threshold_hours, weekly_policy.weekly_tiers
        )
        if not weekly_buckets:
            continue

        # Every day in the week needs a "regular hours" entry to
        # reclassify from, even days outside the requested range whose
        # own line item is never emitted (see this function's
        # docstring).
        for business_date in week_dates:
            if business_date not in regular_hours_after_weekly:
                regular_hours_after_weekly[business_date] = get_breakdown(business_date)[2]

        # Reclassify weekly-OT-eligible hours out of the regular pool
        # they'd otherwise be paid at, tracking exactly which day (and
        # which tier) each reclassified hour came from — needed to
        # prorate correctly (see module docstring).
        #
        # Two conventions are applied in lockstep:
        #   - which day an hour is reclassified from: by convention, the
        #     hours that pushed the week over its threshold are the ones
        #     worked latest in the week, so days are walked backward
        #     from the end of the week.
        #   - which multiplier tier an hour belongs to: tiers are
        #     ordered by magnitude above the threshold (lowest tier
        #     first), and the highest tier — the "most excess" hours —
        #     corresponds to the same latest-in-week hours by the same
        #     convention, so tiers are walked in reverse (highest first)
        #     while days are walked backward, together.
        #
        # This produces an exact (day, tier) -> hours allocation instead
        # of a single lump sum, so a weekly-OT LineItem can be attributed
        # to the actual day its hours came from and only emitted for
        # days inside the requested range.
        remaining_regular = {
            business_date: regular_hours_after_weekly[business_date]
            for business_date in week_dates
        }
        day_queue = list(reversed(week_dates))
        day_index = 0
        allocation: dict[tuple[date, int], Decimal] = {}
        reclassified_hours: dict[date, Decimal] = {}

        for tier_index in range(len(weekly_buckets), 0, -1):
            tier_needed = weekly_buckets[tier_index - 1].hours
            while tier_needed > 0 and day_index < len(day_queue):
                business_date = day_queue[day_index]
                available = remaining_regular[business_date]
                take = min(available, tier_needed)
                if take > 0:
                    allocation[(business_date, tier_index)] = take
                    reclassified_hours[business_date] = (
                        reclassified_hours.get(business_date, Decimal("0")) + take
                    )
                    remaining_regular[business_date] = available - take
                    tier_needed -= take
                if remaining_regular[business_date] <= 0:
                    day_index += 1

        for business_date, hours in reclassified_hours.items():
            regular_hours_after_weekly[business_date] -= hours

        for (business_date, tier_index), hours in allocation.items():
            if not (start_date <= business_date <= end_date):
                continue
            rate = get_breakdown(business_date)[0]
            multiplier = weekly_buckets[tier_index - 1].multiplier
            weekly_line_items.append(
                _make_line_item(
                    employee_id,
                    business_date,
                    f"weekly_ot_{tier_index}",
                    hours,
                    rate,
                    multiplier,
                )
            )

    line_items: list[LineItem] = []
    for business_date in requested_dates:
        rate, _policy, _regular_hours, ot_buckets = get_breakdown(business_date)
        regular_hours = regular_hours_after_weekly[business_date]
        line_items.extend(
            _daily_line_items(employee_id, business_date, rate, regular_hours, ot_buckets)
        )
    line_items.extend(weekly_line_items)

    line_items.sort(key=lambda item: (item.business_date, item.category))
    return line_items


def department_cost_summary(
    scope: AccessScope, department_id: int, start_date: date, end_date: date
) -> DepartmentCostSummary:
    """Total labor cost for every *configured* employee in a department
    over a date range. Admin/manager (manager restricted to a department
    they manage) — enforces confirmed rule A4 by returning **only the
    total**, never a per-employee breakdown, never an hourly rate.

    Round A fix: ``range_cost_for_employee`` still raises
    ``ValidationError`` for an employee who genuinely worked hours with
    no pay rate or overtime policy configured for them somewhere in the
    range. Previously that one employee's gap propagated straight out of
    this function and blanked the *entire* department's total. Per
    employee ``ValidationError`` is now caught here (mirroring
    ``reports.overtime_summary``'s existing pattern) so the total still
    reflects every employee who *is* fully configured, with the gap
    surfaced as an explicit count rather than silently discarding
    everyone else's figures.

    Residual limitation, documented rather than silently ignored: this
    function only guarantees it never *directly* returns an individual
    rate or per-employee figure. It cannot mathematically prevent a
    manager who separately knows one employee's hours for the queried
    range from dividing this total by those hours to estimate a rate —
    that inference is only as hard as the department actually being a
    multi-employee, multi-day aggregate in practice. The real mitigation
    is at the workflow level (this is intended for department-wide
    reporting, and the only route that exposes a single employee's own
    breakdown is the separate, explicitly admin-only detail view), not a
    guarantee enforced here.
    """
    if scope.role not in ("admin", "manager"):
        abort(403)
    if scope.role == "manager" and department_id not in scope.department_ids:
        abort(404)

    # Validated here, once, before the per-employee loop below: a bad
    # caller-supplied date range is a request error, not a per-employee
    # configuration gap, so it must not be swallowed by the per-employee
    # ValidationError isolation further down.
    if end_date < start_date:
        raise ValidationError("end_date must be on or after start_date.")

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

    employee_ids = [
        row[0]
        for row in db.session.query(Employee.id)
        .filter(
            Employee.organization_id == scope.organization_id,
            Employee.department_id == department_id,
        )
        .all()
    ]

    total = Decimal("0.00")
    unconfigured_employee_count = 0
    for employee_id in employee_ids:
        try:
            line_items = range_cost_for_employee(scope, employee_id, start_date, end_date)
        except ValidationError:
            unconfigured_employee_count += 1
            continue
        for line_item in line_items:
            total += line_item.cost
    return DepartmentCostSummary(
        total=total, unconfigured_employee_count=unconfigured_employee_count
    )
