"""Integration tests for app.services.labor_cost — the crux of this
milestone: money rounding (confirmed rule A12) and weekly overtime
carried through to Decimal cost figures.

The pure hours/tiering math is already unit-tested in
tests/unit/test_overtime.py; these tests focus on what
app.services.labor_cost adds on top of it — resolving pay rates,
rounding each line item independently, and reclassifying weekly-OT
hours out of the daily "regular" bucket so no worked hour is priced
twice.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.auth.scope import AccessScope
from app.services import labor_cost as labor_cost_service
from app.services.errors import ValidationError
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_organization,
    make_overtime_policy,
    make_overtime_tier,
    make_pay_rate,
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


def _default_policy(session, org):
    """The confirmed default policy shape used throughout this project:
    8h daily threshold (0-2h beyond @1.5x, 2h+ @2.0x), 40h weekly
    threshold (beyond @1.5x), week starting Monday.
    """
    policy = make_overtime_policy(
        session,
        organization=org,
        daily_threshold_hours=Decimal("8.00"),
        weekly_threshold_hours=Decimal("40.00"),
        week_start_day=0,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    make_overtime_tier(
        session,
        policy=policy,
        scope="daily",
        tier_order=0,
        from_hours=Decimal("0.00"),
        to_hours=Decimal("2.00"),
        multiplier=Decimal("1.50"),
    )
    make_overtime_tier(
        session,
        policy=policy,
        scope="daily",
        tier_order=1,
        from_hours=Decimal("2.00"),
        to_hours=None,
        multiplier=Decimal("2.00"),
    )
    make_overtime_tier(
        session,
        policy=policy,
        scope="weekly",
        tier_order=0,
        from_hours=Decimal("0.00"),
        to_hours=None,
        multiplier=Decimal("1.50"),
    )
    return policy


def _worked_hours_entry(session, org, employee, admin, business_date, hours):
    start = datetime(
        business_date.year, business_date.month, business_date.day, 8, 0, tzinfo=timezone.utc
    )
    end = start + timedelta(hours=hours)
    make_attendance_entry(
        session,
        organization=org,
        employee=employee,
        created_by=admin,
        started_at=start,
        ended_at=end,
        business_date=business_date,
    )


class TestDailyCostForEmployee:
    def test_exactly_eight_hours_produces_one_regular_line_item(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )
        _worked_hours_entry(db_session, org, employee, admin, date(2026, 1, 5), 8)

        scope = _scope("admin", org.id, user_id=admin.id)
        line_items = labor_cost_service.daily_cost_for_employee(
            scope, employee.id, date(2026, 1, 5)
        )

        assert len(line_items) == 1
        item = line_items[0]
        assert item.category == "regular"
        assert item.hours == Decimal("8")
        assert item.rate == Decimal("20.0000")
        assert item.multiplier == Decimal("1")
        assert item.cost == Decimal("160.00")

    def test_eleven_hours_produces_three_independently_rounded_line_items(
        self, db_session
    ):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )
        _worked_hours_entry(db_session, org, employee, admin, date(2026, 1, 5), 11)

        scope = _scope("admin", org.id, user_id=admin.id)
        line_items = labor_cost_service.daily_cost_for_employee(
            scope, employee.id, date(2026, 1, 5)
        )

        by_category = {item.category: item for item in line_items}
        assert set(by_category) == {"regular", "daily_ot_1", "daily_ot_2"}

        regular = by_category["regular"]
        ot1 = by_category["daily_ot_1"]
        ot2 = by_category["daily_ot_2"]

        assert regular.hours == Decimal("8") and regular.cost == Decimal("160.00")
        assert ot1.hours == Decimal("2") and ot1.multiplier == Decimal("1.5")
        assert ot1.cost == Decimal("60.00")
        assert ot2.hours == Decimal("1") and ot2.multiplier == Decimal("2.0")
        assert ot2.cost == Decimal("40.00")

        total = regular.cost + ot1.cost + ot2.cost
        assert total == Decimal("260.00")

    def test_rounding_each_line_item_separately_differs_from_rounding_a_single_total(
        self, db_session
    ):
        """Confirmed rule A12's actual crux: a rate chosen so that
        rounding each of the three line items to the cent independently
        gives a different (and correct) total than rounding one combined
        raw total would. 8h regular + 2h@1.5x + 1h@2.0x at
        $10.0005/hour:

        - regular: 8 * 10.0005 = 80.0040 -> rounds to 80.00
        - daily_ot_1: 2 * 10.0005 * 1.5 = 30.00150 -> rounds to 30.00
        - daily_ot_2: 1 * 10.0005 * 2.0 = 20.00100 -> rounds to 20.00
        - sum of the three already-rounded line items: 130.00

        Rounding the unrounded combined total instead:
        80.0040 + 30.00150 + 20.00100 = 130.00650 -> rounds to 130.01

        The two approaches disagree by one cent; this asserts the
        actually-implemented per-line-item result (130.00), not the
        single-total-rounding alternative (130.01).
        """
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("10.0005"),
            effective_from=date(2020, 1, 1),
        )
        _worked_hours_entry(db_session, org, employee, admin, date(2026, 1, 5), 11)

        scope = _scope("admin", org.id, user_id=admin.id)
        line_items = labor_cost_service.daily_cost_for_employee(
            scope, employee.id, date(2026, 1, 5)
        )

        total_of_rounded_line_items = sum(
            (item.cost for item in line_items), Decimal("0.00")
        )
        assert total_of_rounded_line_items == Decimal("130.00")

        raw_total = sum(
            (item.hours * item.rate * item.multiplier for item in line_items),
            Decimal("0"),
        )
        rounded_single_total = raw_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert rounded_single_total == Decimal("130.01")
        assert total_of_rounded_line_items != rounded_single_total

    def test_no_pay_rate_configured_raises_validation_error_not_a_silent_zero(
        self, db_session
    ):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        _worked_hours_entry(db_session, org, employee, admin, date(2026, 1, 5), 8)

        scope = _scope("admin", org.id, user_id=admin.id)
        with pytest.raises(ValidationError):
            labor_cost_service.daily_cost_for_employee(scope, employee.id, date(2026, 1, 5))

    def test_no_overtime_policy_configured_raises_validation_error(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )
        _worked_hours_entry(db_session, org, employee, admin, date(2026, 1, 5), 8)

        scope = _scope("admin", org.id, user_id=admin.id)
        with pytest.raises(ValidationError):
            labor_cost_service.daily_cost_for_employee(scope, employee.id, date(2026, 1, 5))


class TestRangeCostForEmployee:
    def test_weekly_overtime_does_not_double_count_daily_overtime_hours(self, db_session):
        """Mirrors tests/unit/test_overtime.py's weekly-OT scenario: six
        9h days (Mon-Sat). Each day: 8h regular + 1h daily OT @1.5x.
        Regular hours across the week total 48h, 8h beyond the 40h
        weekly threshold -> one weekly-OT bucket of 8h @1.5x.

        The range requested is Monday-Saturday; Sunday (needed to
        compute the full week) is a rest day with zero hours but must
        still have a pay rate/policy configured, since correctly
        computing weekly overtime requires the whole week's data.
        """
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )

        monday = date(2026, 1, 5)
        for offset in range(6):
            _worked_hours_entry(
                db_session, org, employee, admin, monday + timedelta(days=offset), 9
            )

        scope = _scope("admin", org.id, user_id=admin.id)
        saturday = monday + timedelta(days=5)
        line_items = labor_cost_service.range_cost_for_employee(
            scope, employee.id, monday, saturday
        )

        weekly_items = [item for item in line_items if item.category.startswith("weekly_ot")]
        daily_ot_items = [item for item in line_items if item.category.startswith("daily_ot")]
        regular_items = [item for item in line_items if item.category == "regular"]

        # One weekly-OT line item: 8h @ 1.5x, attributed to the last day
        # of the week within the requested range (Saturday, since the
        # week's actual end -- Sunday -- falls outside [monday, saturday]).
        assert len(weekly_items) == 1
        assert weekly_items[0].hours == Decimal("8")
        assert weekly_items[0].multiplier == Decimal("1.5")
        assert weekly_items[0].business_date == saturday
        assert weekly_items[0].cost == Decimal("240.00")

        # Six days of daily OT (1h @1.5x each) untouched by the weekly
        # reclassification -- daily OT and weekly OT never overlap.
        assert len(daily_ot_items) == 6
        assert all(item.hours == Decimal("1") for item in daily_ot_items)
        assert sum((item.cost for item in daily_ot_items), Decimal("0.00")) == Decimal(
            "180.00"
        )

        # Regular hours: 5 full 8h days, plus Saturday's regular hours
        # entirely reclassified into the weekly-OT bucket above (its 8h
        # of would-be-regular time is exactly the weekly-OT amount), so
        # Saturday contributes no "regular" line item at all.
        assert len(regular_items) == 5
        assert {item.business_date for item in regular_items} == {
            monday + timedelta(days=i) for i in range(5)
        }
        assert sum((item.cost for item in regular_items), Decimal("0.00")) == Decimal(
            "800.00"
        )

        # No worked hour is priced twice: total hours across every line
        # item for the six requested days equals 6 * 9 = 54 exactly.
        total_hours = sum((item.hours for item in line_items), Decimal("0"))
        assert total_hours == Decimal("54")

        # And the total cost matches the hand-computed figure: 40 regular
        # hours + 6 daily-OT hours (1.5x) + 8 weekly-OT hours (1.5x), all
        # at $20/hour.
        total_cost = sum((item.cost for item in line_items), Decimal("0.00"))
        assert total_cost == Decimal("1220.00")

    def test_end_date_before_start_date_is_rejected(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, user_id=admin.id)

        with pytest.raises(ValidationError):
            labor_cost_service.range_cost_for_employee(
                scope, employee.id, date(2026, 1, 5), date(2026, 1, 1)
            )


class TestWeeklyOvertimeProration:
    """Round A fix: weekly-OT hours must only be billed for the portion
    of reclassified hours that actually fall inside the requested range,
    attributed to the specific day they came from — never lumped onto a
    single end-of-week date regardless of whether that date was
    requested, and never double-billed across two adjacent requests that
    together span a full week.

    Scenario shared by all tests below: a custom policy with an
    artificially low 21h weekly threshold (so a plain 8h/day, 7-day week
    triggers weekly OT without needing daily OT to complicate the
    numbers) and a high 24h daily threshold (so no daily OT ever
    triggers). Monday-Sunday each 8h worked, all "regular" per day in
    isolation -> 56h total regular hours across the week, 56 - 21 = 35h
    weekly-OT eligible, walked backward from Sunday: Sun 8h, Sat 8h, Fri
    8h, Thu 8h, Wed 3h (partial) = 35h. Monday and Tuesday are untouched.
    """

    def _custom_policy(self, session, org):
        policy = make_overtime_policy(
            session,
            organization=org,
            daily_threshold_hours=Decimal("24.00"),
            weekly_threshold_hours=Decimal("21.00"),
            week_start_day=0,
            effective_from=date(2020, 1, 1),
            effective_to=None,
        )
        make_overtime_tier(
            session,
            policy=policy,
            scope="weekly",
            tier_order=0,
            from_hours=Decimal("0.00"),
            to_hours=None,
            multiplier=Decimal("1.50"),
        )
        return policy

    def _heavy_week(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        self._custom_policy(db_session, org)
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )
        monday = date(2026, 1, 5)
        for offset in range(7):
            _worked_hours_entry(db_session, org, employee, admin, monday + timedelta(days=offset), 8)
        scope = _scope("admin", org.id, user_id=admin.id)
        return scope, employee, monday

    def test_single_day_query_does_not_bill_weekly_ot_for_hours_worked_elsewhere(
        self, db_session
    ):
        """Monday alone never contributed any reclassified hours (only
        Wed-Sun did), so querying just Monday must return zero weekly-OT
        line items -- not the whole week's 35h lumped onto it.
        """
        scope, employee, monday = self._heavy_week(db_session)

        line_items = labor_cost_service.range_cost_for_employee(
            scope, employee.id, monday, monday
        )

        weekly_items = [item for item in line_items if item.category.startswith("weekly_ot")]
        regular_items = [item for item in line_items if item.category == "regular"]

        assert weekly_items == []
        assert len(regular_items) == 1
        assert regular_items[0].hours == Decimal("8")
        assert regular_items[0].cost == Decimal("160.00")

    def test_partial_week_query_only_bills_its_own_share_of_reclassified_hours(
        self, db_session
    ):
        """Wednesday's 8h were only partially (3h) reclassified into
        weekly OT; the other 5h remain "regular". A query for just
        Wednesday must reflect exactly that split.
        """
        scope, employee, monday = self._heavy_week(db_session)
        wednesday = monday + timedelta(days=2)

        line_items = labor_cost_service.range_cost_for_employee(
            scope, employee.id, wednesday, wednesday
        )

        weekly_items = [item for item in line_items if item.category.startswith("weekly_ot")]
        regular_items = [item for item in line_items if item.category == "regular"]

        assert len(weekly_items) == 1
        assert weekly_items[0].hours == Decimal("3")
        assert weekly_items[0].business_date == wednesday
        assert weekly_items[0].cost == Decimal("90.00")

        assert len(regular_items) == 1
        assert regular_items[0].hours == Decimal("5")
        assert regular_items[0].cost == Decimal("100.00")

    def test_adjacent_disjoint_ranges_together_equal_the_full_week(self, db_session):
        """cost(mon..sun) == cost(mon..wed) + cost(thu..sun): the
        invariant a lump-sum, end-of-week attribution would violate by
        billing the full week's weekly-OT hours in both halves.
        """
        scope, employee, monday = self._heavy_week(db_session)
        wednesday = monday + timedelta(days=2)
        thursday = monday + timedelta(days=3)
        sunday = monday + timedelta(days=6)

        full_week = labor_cost_service.range_cost_for_employee(
            scope, employee.id, monday, sunday
        )
        first_half = labor_cost_service.range_cost_for_employee(
            scope, employee.id, monday, wednesday
        )
        second_half = labor_cost_service.range_cost_for_employee(
            scope, employee.id, thursday, sunday
        )

        full_week_total = sum((item.cost for item in full_week), Decimal("0.00"))
        split_total = sum(
            (item.cost for item in first_half + second_half), Decimal("0.00")
        )

        assert full_week_total == split_total
        # Sanity: this is the actual hand-computed total, not just an
        # internally-consistent-but-wrong number -- 21h regular @ $20 +
        # 35h weekly OT @ $20 * 1.5.
        assert full_week_total == Decimal("21") * 20 + Decimal("35") * 20 * Decimal("1.5")

        # And the split must not double-count: the naive pre-fix
        # behavior (each half re-billing the full week's 35h) would make
        # split_total roughly double full_week_total instead of equal.
        assert split_total != full_week_total * 2


class TestZeroHourDayDoesNotRequireConfiguration:
    """Round A fix: a day with zero worked hours needs no pay rate or
    overtime policy -- there's nothing to price -- even though
    range_cost_for_employee must still expand to every day of a touched
    week to compute weekly OT correctly.
    """

    def test_employee_hired_mid_week_does_not_blank_the_whole_week(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)

        monday = date(2026, 1, 5)
        wednesday = monday + timedelta(days=2)
        sunday = monday + timedelta(days=6)
        # Hired Wednesday: no pay rate at all covers Monday/Tuesday, and
        # no hours are worked on those two days either.
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=wednesday,
        )
        for offset in range(2, 7):
            _worked_hours_entry(db_session, org, employee, admin, monday + timedelta(days=offset), 8)

        scope = _scope("admin", org.id, user_id=admin.id)
        # Should not raise despite Monday/Tuesday having no configured
        # pay rate -- they have zero worked hours.
        line_items = labor_cost_service.range_cost_for_employee(
            scope, employee.id, monday, sunday
        )

        regular_items = [item for item in line_items if item.category == "regular"]
        assert {item.business_date for item in regular_items} == {
            wednesday + timedelta(days=i) for i in range(5)
        }
        assert sum((item.cost for item in regular_items), Decimal("0.00")) == Decimal(
            "800.00"
        )
        # 40h total (5 * 8h), exactly at the 40h weekly threshold -- no
        # weekly OT triggered.
        assert [item for item in line_items if item.category.startswith("weekly_ot")] == []


class TestDepartmentCostSummary:
    def test_totals_every_employee_in_the_department(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)

        employee_a = make_employee(db_session, organization=org, department=department)
        employee_b = make_employee(db_session, organization=org, department=department)
        for employee in (employee_a, employee_b):
            make_pay_rate(
                db_session,
                organization=org,
                employee=employee,
                hourly_rate=Decimal("20.0000"),
                effective_from=date(2020, 1, 1),
            )
            _worked_hours_entry(db_session, org, employee, admin, date(2026, 1, 5), 8)

        scope = _scope("admin", org.id, user_id=admin.id)
        summary = labor_cost_service.department_cost_summary(
            scope, department.id, date(2026, 1, 5), date(2026, 1, 5)
        )

        assert summary.total == Decimal("320.00")
        assert summary.unconfigured_employee_count == 0

    def test_manager_can_only_summarize_a_department_they_manage(self, db_session):
        from werkzeug.exceptions import NotFound

        org = make_organization(db_session)
        other_department = make_department(db_session, organization=org)
        manager = make_user(db_session, organization=org, role="manager")
        scope = _scope("manager", org.id, user_id=manager.id)

        with pytest.raises(NotFound):
            labor_cost_service.department_cost_summary(
                scope, other_department.id, date(2026, 1, 5), date(2026, 1, 5)
            )

    def test_employee_role_cannot_call_department_cost_summary(self, db_session):
        from werkzeug.exceptions import Forbidden

        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        scope = _scope("employee", org.id, employee_id=employee.id)

        with pytest.raises(Forbidden):
            labor_cost_service.department_cost_summary(
                scope, department.id, date(2026, 1, 5), date(2026, 1, 5)
            )

    def test_employee_hired_mid_week_no_longer_blanks_department_total(self, db_session):
        """Round A fix: a department with one employee hired partway
        through a queried week must still return the fully-configured
        employees' correct total, not None for the whole department.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)

        monday = date(2026, 1, 5)
        wednesday = monday + timedelta(days=2)
        sunday = monday + timedelta(days=6)

        full_week_employee = make_employee(
            db_session, organization=org, department=department
        )
        make_pay_rate(
            db_session,
            organization=org,
            employee=full_week_employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )
        for offset in range(7):
            _worked_hours_entry(
                db_session, org, full_week_employee, admin, monday + timedelta(days=offset), 8
            )

        mid_week_hire = make_employee(db_session, organization=org, department=department)
        make_pay_rate(
            db_session,
            organization=org,
            employee=mid_week_hire,
            hourly_rate=Decimal("20.0000"),
            effective_from=wednesday,
        )
        for offset in range(2, 7):
            _worked_hours_entry(
                db_session, org, mid_week_hire, admin, monday + timedelta(days=offset), 8
            )

        scope = _scope("admin", org.id, user_id=admin.id)
        summary = labor_cost_service.department_cost_summary(
            scope, department.id, monday, sunday
        )

        # full_week_employee: 56h/week exceeds the 40h weekly threshold
        # by 16h (reclassified from Sat+Sun @1.5x) -> 40h regular @$20
        # ($800) + 16h weekly OT @$20*1.5 ($480) = $1280. mid_week_hire:
        # 40h/week (Wed-Sun), exactly at the threshold, no weekly OT ->
        # $800. Total: $2080.
        assert summary.total == Decimal("2080.00")
        assert summary.unconfigured_employee_count == 0

    def test_one_unconfigured_employee_does_not_blank_the_rest_of_the_department(
        self, db_session
    ):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)

        configured_employee = make_employee(
            db_session, organization=org, department=department
        )
        make_pay_rate(
            db_session,
            organization=org,
            employee=configured_employee,
            hourly_rate=Decimal("20.0000"),
            effective_from=date(2020, 1, 1),
        )
        _worked_hours_entry(db_session, org, configured_employee, admin, date(2026, 1, 5), 8)

        # This employee actually worked hours but has no pay rate at all
        # -- a genuine configuration gap, not a zero-hour non-issue.
        unconfigured_employee = make_employee(
            db_session, organization=org, department=department
        )
        _worked_hours_entry(
            db_session, org, unconfigured_employee, admin, date(2026, 1, 5), 8
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        summary = labor_cost_service.department_cost_summary(
            scope, department.id, date(2026, 1, 5), date(2026, 1, 5)
        )

        assert summary.total == Decimal("160.00")
        assert summary.unconfigured_employee_count == 1
