"""Integration tests for app.services.reports — DB + authorization.

Confirms each new aggregation is a faithful composition of the already-
verified scheduling/attendance/leave/working_hours/overtime/labor_cost
services against a small constructed scenario, not a new business rule.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.auth.scope import AccessScope
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
