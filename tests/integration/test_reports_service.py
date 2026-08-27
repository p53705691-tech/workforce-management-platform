"""Integration tests for app.services.reports — DB + authorization.

Confirms each new aggregation is a faithful composition of the already-
verified scheduling/attendance/leave/working_hours/overtime/labor_cost
services against a small constructed scenario, not a new business rule.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from freezegun import freeze_time
from werkzeug.exceptions import Forbidden

from app.auth.scope import AccessScope
from app.services import audit as audit_service
from app.services import reports as report_service
from app.services.scheduling import business_date_for, organization_timezone
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_leave_request,
    make_leave_type,
    make_organization,
    make_overtime_policy,
    make_overtime_tier,
    make_pay_rate,
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


def _today_for(org):
    """"Today" per the org's own timezone, matching
    ``reports.today_business_date`` exactly, so a test run near a
    timezone boundary is never flaky.
    """
    tz = organization_timezone(_scope("admin", org.id))
    return business_date_for(datetime.now(timezone.utc), tz)


def _default_policy(session, org, **overrides):
    defaults = {
        "daily_threshold_hours": Decimal("8.00"),
        "weekly_threshold_hours": Decimal("40.00"),
        "week_start_day": 0,
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
    }
    defaults.update(overrides)
    policy = make_overtime_policy(session, organization=org, **defaults)
    make_overtime_tier(
        session, policy=policy, scope="daily", tier_order=0,
        from_hours=Decimal("0.00"), to_hours=Decimal("2.00"), multiplier=Decimal("1.50"),
    )
    make_overtime_tier(
        session, policy=policy, scope="daily", tier_order=1,
        from_hours=Decimal("2.00"), to_hours=None, multiplier=Decimal("2.00"),
    )
    make_overtime_tier(
        session, policy=policy, scope="weekly", tier_order=0,
        from_hours=Decimal("0.00"), to_hours=None, multiplier=Decimal("1.50"),
    )
    return policy


class TestWhoIsWorkingToday:
    @freeze_time("2026-01-15 12:00:00")
    def test_returns_only_published_shifts_for_today(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        draft_employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        ends_at = starts_at + timedelta(hours=8)

        make_shift(
            db_session, organization=org, department=department, employee=employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )
        make_shift(
            db_session, organization=org, department=department, employee=draft_employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="draft",
        )

        result = report_service.who_is_working_today(_scope("admin", org.id))

        assert [s.employee_id for s in result] == [employee.id]

    @freeze_time("2026-01-15 12:00:00")
    def test_filters_by_department(self, db_session):
        org = make_organization(db_session)
        dept_a = make_department(db_session, organization=org)
        dept_b = make_department(db_session, organization=org)
        employee_a = make_employee(db_session, organization=org, department=dept_a)
        employee_b = make_employee(db_session, organization=org, department=dept_b)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        ends_at = starts_at + timedelta(hours=8)

        for department, employee in ((dept_a, employee_a), (dept_b, employee_b)):
            make_shift(
                db_session, organization=org, department=department, employee=employee,
                created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
                status="published", published_at=datetime.now(timezone.utc),
            )

        result = report_service.who_is_working_today(
            _scope("admin", org.id), department_id=dept_a.id
        )

        assert [s.employee_id for s in result] == [employee_a.id]

    @freeze_time("2026-01-15 07:00:00")
    def test_excludes_a_shift_that_has_not_started_yet(self, db_session):
        """A shift starting later today is not yet "working" — see the
        module docstring on why who_is_working_today requires the shift
        to actually be in progress, not merely scheduled for today.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, time(9, 0), tzinfo=timezone.utc)
        ends_at = starts_at + timedelta(hours=8)

        make_shift(
            db_session, organization=org, department=department, employee=employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )

        result = report_service.who_is_working_today(_scope("admin", org.id))

        assert result == []

    @freeze_time("2026-01-15 23:00:00")
    def test_excludes_a_shift_that_already_ended(self, db_session):
        """QA finding: a shift that ended hours ago must not still render
        as "Working" on the dashboard.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, time(9, 0), tzinfo=timezone.utc)
        ends_at = starts_at + timedelta(hours=8)

        make_shift(
            db_session, organization=org, department=department, employee=employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )

        result = report_service.who_is_working_today(_scope("admin", org.id))

        assert result == []


class TestWhoIsOnLeaveToday:
    def test_returns_only_approved_requests_covering_today(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        on_leave_employee = make_employee(db_session, organization=org, department=department)
        pending_employee = make_employee(db_session, organization=org, department=department)
        past_leave_employee = make_employee(db_session, organization=org, department=department)
        leave_type = make_leave_type(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

        make_leave_request(
            db_session, organization=org, employee=on_leave_employee, leave_type=leave_type,
            requested_by=admin, status="approved",
            decided_by_user_id=admin.id, decided_at=datetime.now(timezone.utc),
            starts_at=today_start, ends_at=today_start + timedelta(hours=23, minutes=59),
        )
        make_leave_request(
            db_session, organization=org, employee=pending_employee, leave_type=leave_type,
            requested_by=admin, status="pending",
            starts_at=today_start, ends_at=today_start + timedelta(hours=23, minutes=59),
        )
        make_leave_request(
            db_session, organization=org, employee=past_leave_employee, leave_type=leave_type,
            requested_by=admin, status="approved",
            decided_by_user_id=admin.id, decided_at=datetime.now(timezone.utc),
            starts_at=today_start - timedelta(days=10),
            ends_at=today_start - timedelta(days=9),
        )

        result = report_service.who_is_on_leave_today(_scope("admin", org.id))

        assert [lr.employee_id for lr in result] == [on_leave_employee.id]


class TestWhoIsAbsentToday:
    @freeze_time("2026-01-15 12:00:00")
    def test_excludes_employee_with_a_matching_attendance_entry(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        worked_employee = make_employee(db_session, organization=org, department=department)
        absent_employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        ends_at = starts_at + timedelta(hours=8)

        worked_shift = make_shift(
            db_session, organization=org, department=department, employee=worked_employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )
        make_shift(
            db_session, organization=org, department=department, employee=absent_employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )
        make_attendance_entry(
            db_session, organization=org, employee=worked_employee, shift=worked_shift,
            created_by=admin, started_at=starts_at, ended_at=ends_at, business_date=today,
            status="closed",
        )

        result = report_service.who_is_absent_today(_scope("admin", org.id))

        assert [e.id for e in result] == [absent_employee.id]

    @freeze_time("2026-01-15 12:00:00")
    def test_does_not_report_a_present_employee_absent_when_shift_id_is_unmatched(
        self, db_session
    ):
        """Round B fix: attendance._match_shift leaves shift_id NULL when
        the clock-in falls outside its 60-minute grace window (or when
        more than one shift could match) -- that means "could not decide
        which shift", not "did not work". Before this fix, such an
        employee -- clocked in, present -- was reported as absent.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        early_clock_in_employee = make_employee(
            db_session, organization=org, department=department
        )
        two_shift_employee = make_employee(
            db_session, organization=org, department=department
        )
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        starts_at = today_start + timedelta(hours=9)
        ends_at = starts_at + timedelta(hours=8)

        make_shift(
            db_session, organization=org, department=department,
            employee=early_clock_in_employee, created_by=admin,
            starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )
        # Clocked in 90 minutes early -- outside the 60-minute grace
        # window attendance.clock_in uses for shift-matching -- so the
        # resulting entry's shift_id is NULL, not because they're absent.
        make_attendance_entry(
            db_session, organization=org, employee=early_clock_in_employee,
            shift=None, created_by=admin,
            started_at=starts_at - timedelta(minutes=90), ended_at=ends_at,
            business_date=today, status="closed",
        )

        # Two shifts the same day -- clock_in's own matching would refuse
        # to guess between them and leave shift_id NULL, but the employee
        # is clearly working (they're clocked in against one of them).
        second_shift_starts = ends_at + timedelta(hours=1)
        make_shift(
            db_session, organization=org, department=department,
            employee=two_shift_employee, created_by=admin,
            starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )
        make_shift(
            db_session, organization=org, department=department,
            employee=two_shift_employee, created_by=admin,
            starts_at=second_shift_starts, ends_at=second_shift_starts + timedelta(hours=4),
            business_date=today, status="published", published_at=datetime.now(timezone.utc),
        )
        make_attendance_entry(
            db_session, organization=org, employee=two_shift_employee,
            shift=None, created_by=admin,
            started_at=starts_at, ended_at=ends_at,
            business_date=today, status="closed",
        )

        result = report_service.who_is_absent_today(_scope("admin", org.id))

        assert result == []

    @freeze_time("2026-01-15 12:00:00")
    def test_excludes_employee_on_approved_leave_covering_today(self, db_session):
        """An employee who is scheduled *and* on approved leave today is a
        different classification (on leave), not "absent" — see
        ``who_is_absent_today``'s docstring.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        on_leave_employee = make_employee(db_session, organization=org, department=department)
        absent_employee = make_employee(db_session, organization=org, department=department)
        leave_type = make_leave_type(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        starts_at = today_start + timedelta(hours=9)
        ends_at = starts_at + timedelta(hours=8)

        for employee in (on_leave_employee, absent_employee):
            make_shift(
                db_session, organization=org, department=department, employee=employee,
                created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
                status="published", published_at=datetime.now(timezone.utc),
            )

        # Constructed directly (bypassing approve_leave's own conflict
        # check, which would normally refuse to approve leave that
        # overlaps a published shift) purely to exercise
        # who_is_absent_today's classification of this state, not the
        # leave-approval workflow itself.
        make_leave_request(
            db_session, organization=org, employee=on_leave_employee, leave_type=leave_type,
            requested_by=admin, status="approved",
            decided_by_user_id=admin.id, decided_at=datetime.now(timezone.utc),
            starts_at=today_start, ends_at=today_start + timedelta(hours=23, minutes=59),
        )

        result = report_service.who_is_absent_today(_scope("admin", org.id))

        assert [e.id for e in result] == [absent_employee.id]

    @freeze_time("2026-01-15 07:00:00")
    def test_excludes_an_employee_whose_shift_has_not_started_yet(self, db_session):
        """Data/business-logic finding: an employee cannot be "absent"
        from a shift that has not started — before this fix, every
        not-yet-started employee was flagged absent (and, since
        who_is_working_today used to share the same unfiltered shift
        list, simultaneously counted as "working" too).
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, time(9, 0), tzinfo=timezone.utc)
        ends_at = starts_at + timedelta(hours=8)

        make_shift(
            db_session, organization=org, department=department, employee=employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )

        result = report_service.who_is_absent_today(_scope("admin", org.id))

        assert result == []

    @freeze_time("2026-01-15 23:00:00")
    def test_still_reports_a_no_show_absent_after_their_shift_has_ended(self, db_session):
        """A no-show must stay flagged absent for the rest of the day,
        not just while their shift happens to still be in progress —
        this is exactly why who_is_absent_today does not simply reuse
        who_is_working_today's (now narrower) in-progress-only window.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        starts_at = datetime.combine(today, time(9, 0), tzinfo=timezone.utc)
        ends_at = starts_at + timedelta(hours=8)

        make_shift(
            db_session, organization=org, department=department, employee=employee,
            created_by=admin, starts_at=starts_at, ends_at=ends_at, business_date=today,
            status="published", published_at=datetime.now(timezone.utc),
        )

        result = report_service.who_is_absent_today(_scope("admin", org.id))

        assert [e.id for e in result] == [employee.id]


class TestOvertimeSummary:
    def test_sums_ot_hours_and_never_exposes_rate_or_cost(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        ot_employee = make_employee(db_session, organization=org, department=department)
        no_rate_employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        make_pay_rate(
            db_session, organization=org, employee=ot_employee,
            hourly_rate=Decimal("20.0000"), effective_from=date(2020, 1, 1),
        )
        today = _today_for(org)
        started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        # 10 worked hours: 8 regular + 2 hours of daily overtime (tier 1,
        # 1.5x) per the policy above.
        make_attendance_entry(
            db_session, organization=org, employee=ot_employee, created_by=admin,
            started_at=started_at, ended_at=started_at + timedelta(hours=10),
            business_date=today, status="closed",
        )
        # no_rate_employee must have actually worked hours with no rate
        # configured to genuinely trigger the missing-configuration path
        # under test here — a zero-hour day with no rate configured is a
        # documented non-error (nothing to price), not a gap to isolate.
        make_attendance_entry(
            db_session, organization=org, employee=no_rate_employee, created_by=admin,
            started_at=started_at, ended_at=started_at + timedelta(hours=8),
            business_date=today, status="closed",
        )

        summary = report_service.overtime_summary(
            _scope("admin", org.id), department.id, today, today
        )

        by_employee = {row["employee"].id: row for row in summary}
        assert by_employee[ot_employee.id]["configured"] is True
        assert by_employee[ot_employee.id]["ot_hours"] == Decimal("2.00")
        assert by_employee[no_rate_employee.id]["configured"] is False
        assert by_employee[no_rate_employee.id]["ot_hours"] is None

        for row in summary:
            assert "rate" not in row
            assert "cost" not in row


class TestMyOvertimeHours:
    def test_employee_sees_their_own_overtime_hours(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        _default_policy(db_session, org)
        make_pay_rate(
            db_session, organization=org, employee=employee,
            hourly_rate=Decimal("20.0000"), effective_from=date(2020, 1, 1),
        )
        today = _today_for(org)
        started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=started_at, ended_at=started_at + timedelta(hours=10),
            business_date=today, status="closed",
        )

        result = report_service.my_overtime_hours(
            _scope("employee", org.id, employee_id=employee.id), today, today
        )

        assert result == Decimal("2.00")

    def test_returns_none_without_raising_when_unconfigured(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        started_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=started_at, ended_at=started_at + timedelta(hours=8),
            business_date=today, status="closed",
        )

        result = report_service.my_overtime_hours(
            _scope("employee", org.id, employee_id=employee.id), today, today
        )

        assert result is None

    def test_returns_none_when_scope_has_no_employee_id(self, db_session):
        org = make_organization(db_session)

        result = report_service.my_overtime_hours(
            _scope("admin", org.id), date(2026, 1, 1), date(2026, 1, 1)
        )

        assert result is None


class TestHoursTrend:
    def test_sums_worked_hours_per_day_across_employees_in_the_department(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee_one = make_employee(db_session, organization=org, department=department)
        employee_two = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        yesterday = today - timedelta(days=1)

        def _entry(employee, business_date, hours):
            started_at = datetime.combine(
                business_date, datetime.min.time(), tzinfo=timezone.utc
            ) + timedelta(hours=9)
            make_attendance_entry(
                db_session, organization=org, employee=employee, created_by=admin,
                started_at=started_at, ended_at=started_at + timedelta(hours=hours),
                business_date=business_date, status="closed",
            )

        _entry(employee_one, yesterday, 4)
        _entry(employee_one, today, 3)
        _entry(employee_two, today, 5)

        trend = report_service.hours_trend(
            _scope("admin", org.id), department.id, yesterday, today
        )

        totals_by_date = {row["date"]: row["total_hours"] for row in trend}
        assert totals_by_date[yesterday] == Decimal("4")
        assert totals_by_date[today] == Decimal("8")


class TestCurrentAttendanceStatus:
    def test_none_when_scope_has_no_employee_id(self, db_session):
        org = make_organization(db_session)

        assert report_service.current_attendance_status(_scope("admin", org.id)) is None

    def test_none_when_no_open_entry(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            status="closed",
        )

        status = report_service.current_attendance_status(
            _scope("employee", org.id, employee_id=employee.id)
        )

        assert status is None

    @freeze_time("2026-01-01 14:41:00")
    def test_returns_open_entry_with_elapsed_time(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ended_at=None, business_date=date(2026, 1, 1), status="open",
        )

        status = report_service.current_attendance_status(
            _scope("employee", org.id, employee_id=employee.id)
        )

        assert status["entry"].id == entry.id
        assert status["elapsed_hours"] == 5
        assert status["elapsed_minutes"] == 41

    @freeze_time("2026-01-02 01:00:00")
    def test_finds_an_overnight_entry_still_open_into_the_next_day(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc),
            ended_at=None, business_date=date(2026, 1, 1), status="open",
        )

        status = report_service.current_attendance_status(
            _scope("employee", org.id, employee_id=employee.id)
        )

        assert status["entry"].id == entry.id
        assert status["elapsed_hours"] == 3

    @freeze_time("2026-01-10 09:00:00")
    def test_finds_a_needs_review_entry_left_unresolved_for_several_days(self, db_session):
        """Regression test: a fixed recent-days lookback window used to
        miss a needs_review entry once it fell outside that window,
        wrongly reporting the caller as "not clocked in" even though the
        DB's open-entry unique index still blocks a fresh clock-in and
        only an admin/manager correction can resolve the flag. The
        underlying state is defined by ``ended_at IS NULL``, which has no
        date boundary.
        """
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime(2026, 1, 3, 9, 0, tzinfo=timezone.utc),
            ended_at=None, business_date=date(2026, 1, 3), status="needs_review",
        )

        status = report_service.current_attendance_status(
            _scope("employee", org.id, employee_id=employee.id)
        )

        assert status["entry"].id == entry.id


class TestAttendanceNeedingReview:
    def test_returns_only_needs_review_entries_in_the_lookback_window(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)

        needs_review = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=today, status="needs_review",
        )
        # Same employee cannot have two open/needs_review entries at once
        # (DB-enforced), so a second employee is used for the "closed"
        # and "open" negative cases below.
        closed_employee = make_employee(db_session, organization=org, department=department)
        make_attendance_entry(
            db_session, organization=org, employee=closed_employee, created_by=admin,
            business_date=today, status="closed",
        )
        open_employee = make_employee(db_session, organization=org, department=department)
        make_attendance_entry(
            db_session, organization=org, employee=open_employee, created_by=admin,
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=today, status="open",
        )

        results = report_service.attendance_needing_review(_scope("admin", org.id))

        assert [entry.id for entry in results] == [needs_review.id]

    def test_excludes_entries_older_than_the_lookback_window(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)
        stale_date = today - timedelta(days=report_service._ATTENTION_LOOKBACK_DAYS + 1)

        make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime.combine(stale_date, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=stale_date, status="needs_review",
        )

        results = report_service.attendance_needing_review(_scope("admin", org.id))

        assert results == []

    def test_department_filter_excludes_other_departments(self, db_session):
        org = make_organization(db_session)
        department_a = make_department(db_session, organization=org)
        department_b = make_department(db_session, organization=org)
        employee_a = make_employee(db_session, organization=org, department=department_a)
        employee_b = make_employee(db_session, organization=org, department=department_b)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)

        entry_a = make_attendance_entry(
            db_session, organization=org, employee=employee_a, created_by=admin,
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=today, status="needs_review",
        )
        make_attendance_entry(
            db_session, organization=org, employee=employee_b, created_by=admin,
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=today, status="needs_review",
        )

        results = report_service.attendance_needing_review(
            _scope("admin", org.id), department_id=department_a.id
        )

        assert [entry.id for entry in results] == [entry_a.id]

    def test_manager_only_sees_their_managed_department(self, db_session):
        org = make_organization(db_session)
        managed = make_department(db_session, organization=org)
        unmanaged = make_department(db_session, organization=org)
        managed_employee = make_employee(db_session, organization=org, department=managed)
        unmanaged_employee = make_employee(db_session, organization=org, department=unmanaged)
        admin = make_user(db_session, organization=org, role="admin")
        manager = make_user(db_session, organization=org, role="manager")
        today = _today_for(org)

        managed_entry = make_attendance_entry(
            db_session, organization=org, employee=managed_employee, created_by=admin,
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=today, status="needs_review",
        )
        make_attendance_entry(
            db_session, organization=org, employee=unmanaged_employee, created_by=admin,
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=None, business_date=today, status="needs_review",
        )

        results = report_service.attendance_needing_review(
            _scope("manager", org.id, department_ids=frozenset({managed.id}))
        )

        assert [entry.id for entry in results] == [managed_entry.id]


class TestRecentActivity:
    def test_returns_empty_list_when_nothing_was_logged(self, db_session):
        # Unlike a real HTTP login flow (which always audits itself, so
        # this state is unreachable through the app's own login route —
        # see tests/routes/test_shell.py), calling the service directly
        # with no audit rows at all for the org is the genuine empty case
        # the sidebar's "No recent activity." branch depends on.
        org = make_organization(db_session)
        today = _today_for(org)

        results = report_service.recent_activity(
            _scope("admin", org.id), today - timedelta(days=6), today
        )

        assert results == []

    def test_admin_sees_recent_entries_with_actor_email_resolved(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin", email="chief@example.com")
        today = _today_for(org)

        audit_service.record(
            action="login_success", entity_type="user", entity_id=admin.id,
            organization_id=org.id, actor_user_id=admin.id,
        )
        db_session.flush()

        results = report_service.recent_activity(
            _scope("admin", org.id), today - timedelta(days=6), today
        )

        assert len(results) == 1
        assert results[0]["entry"].action == "login_success"
        assert results[0]["actor_email"] == "chief@example.com"

    def test_entry_with_no_actor_has_no_actor_email(self, db_session):
        org = make_organization(db_session)
        today = _today_for(org)

        audit_service.record(
            action="login_failed", entity_type="user", entity_id=None,
            organization_id=org.id, actor_user_id=None,
        )
        db_session.flush()

        results = report_service.recent_activity(
            _scope("admin", org.id), today - timedelta(days=6), today
        )

        assert results[0]["actor_email"] is None

    def test_respects_limit(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        today = _today_for(org)

        for i in range(3):
            audit_service.record(
                action=f"action_{i}", entity_type="user", entity_id=admin.id,
                organization_id=org.id, actor_user_id=admin.id,
            )
        db_session.flush()

        results = report_service.recent_activity(
            _scope("admin", org.id), today - timedelta(days=6), today, limit=2
        )

        assert len(results) == 2

    def test_manager_is_forbidden(self, db_session):
        org = make_organization(db_session)
        today = _today_for(org)

        with pytest.raises(Forbidden):
            report_service.recent_activity(
                _scope("manager", org.id), today - timedelta(days=6), today
            )


class TestAttendanceEntriesWithContext:
    def test_closed_entry_gets_worked_hours_and_no_lateness(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc),
            break_minutes=30, business_date=date(2026, 1, 1),
        )

        results = report_service.attendance_entries_with_context(
            _scope("admin", org.id), date(2026, 1, 1), date(2026, 1, 1)
        )

        assert len(results) == 1
        row = results[0]
        assert row["entry"].id == entry.id
        # 8h30m elapsed minus 30m break = 8.00h.
        assert row["worked_hours"] == Decimal("8.00")
        assert row["shift"] is None
        assert row["late_minutes"] is None

    def test_open_entry_has_no_worked_hours(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin,
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ended_at=None, business_date=date(2026, 1, 1), status="open",
        )

        results = report_service.attendance_entries_with_context(
            _scope("admin", org.id), date(2026, 1, 1), date(2026, 1, 1)
        )

        assert results[0]["worked_hours"] is None

    def test_late_clock_in_against_matched_shift_reports_late_minutes(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        shift = make_shift(
            db_session, organization=org, employee=employee, created_by=admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            status="published", published_at=datetime.now(timezone.utc),
        )
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, shift=shift, created_by=admin,
            started_at=datetime(2026, 1, 1, 9, 12, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 1),
        )

        results = report_service.attendance_entries_with_context(
            _scope("admin", org.id), date(2026, 1, 1), date(2026, 1, 1)
        )

        row = results[0]
        assert row["entry"].id == entry.id
        assert row["shift"].id == shift.id
        assert row["late_minutes"] == 12

    def test_on_time_or_early_clock_in_against_matched_shift_has_no_lateness(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        shift = make_shift(
            db_session, organization=org, employee=employee, created_by=admin,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            status="published", published_at=datetime.now(timezone.utc),
        )
        make_attendance_entry(
            db_session, organization=org, employee=employee, shift=shift, created_by=admin,
            started_at=datetime(2026, 1, 1, 8, 55, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 1),
        )

        results = report_service.attendance_entries_with_context(
            _scope("admin", org.id), date(2026, 1, 1), date(2026, 1, 1)
        )

        assert results[0]["late_minutes"] is None

    def test_employee_filter_is_passed_through(self, db_session):
        org = make_organization(db_session)
        employee_a = make_employee(db_session, organization=org)
        employee_b = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        entry_a = make_attendance_entry(
            db_session, organization=org, employee=employee_a, created_by=admin,
            business_date=date(2026, 1, 1),
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )
        make_attendance_entry(
            db_session, organization=org, employee=employee_b, created_by=admin,
            business_date=date(2026, 1, 1),
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )

        results = report_service.attendance_entries_with_context(
            _scope("admin", org.id), date(2026, 1, 1), date(2026, 1, 1),
            employee_id=employee_a.id,
        )

        assert [row["entry"].id for row in results] == [entry_a.id]
