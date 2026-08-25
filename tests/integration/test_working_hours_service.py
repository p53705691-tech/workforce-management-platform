"""Integration tests for app.services.working_hours — DB + authorization."""

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from werkzeug.exceptions import NotFound

from app.auth.scope import AccessScope
from app.services import working_hours as working_hours_service
from app.services.errors import ValidationError
from app.services.scheduling import business_date_for
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
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


class TestWorkedSecondsForDay:
    def test_sums_only_closed_entries_for_the_business_date(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 5),
            break_minutes=30,
        )
        # Open entry on the same day: excluded, unresolved time is not
        # paid time until resolved.
        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc),
            ended_at=None,
            status="open",
            business_date=date(2026, 1, 5),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 1, 5)
        )

        # 8h - 30min break = 7.5h = 27000 seconds.
        assert seconds == 27000

    def test_needs_review_entries_are_excluded(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ended_at=None,
            status="needs_review",
            business_date=date(2026, 1, 5),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 1, 5)
        )
        assert seconds == 0

    def test_no_entries_returns_zero(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        scope = _scope("admin", org.id, user_id=admin.id)
        seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 1, 5)
        )
        assert seconds == 0

    def test_overnight_entry_is_attributed_entirely_to_the_start_business_date(
        self, db_session
    ):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 6, 6, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 5),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        start_day_seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 1, 5)
        )
        next_day_seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 1, 6)
        )

        # The full 8h shows up on the start date, none re-split onto the
        # following calendar date.
        assert start_day_seconds == 8 * 3600
        assert next_day_seconds == 0

    def test_employee_cannot_view_another_employees_hours(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        other_employee = make_employee(db_session, organization=org, department=department)

        scope = _scope("employee", org.id, employee_id=employee.id)

        with pytest.raises(NotFound):
            working_hours_service.worked_seconds_for_day(
                scope, other_employee.id, date(2026, 1, 5)
            )

    def test_manager_cannot_view_hours_outside_their_departments(self, db_session):
        org = make_organization(db_session)
        managed_dept = make_department(db_session, organization=org)
        other_dept = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=other_dept)
        manager = make_user(db_session, organization=org, role="manager")

        scope = _scope(
            "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
        )

        with pytest.raises(NotFound):
            working_hours_service.worked_seconds_for_day(
                scope, employee.id, date(2026, 1, 5)
            )


class TestWorkedSecondsForWeek:
    def test_sums_closed_entries_across_the_seven_day_window(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        # Monday 2026-01-05 through Sunday 2026-01-11.
        for day in range(5):
            make_attendance_entry(
                db_session,
                organization=org,
                employee=employee,
                created_by=admin,
                started_at=datetime(2026, 1, 5 + day, 9, 0, tzinfo=timezone.utc),
                ended_at=datetime(2026, 1, 5 + day, 17, 0, tzinfo=timezone.utc),
                business_date=date(2026, 1, 5 + day),
            )
        # Outside the window (the following Monday): must not be counted.
        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 12, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 12),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        seconds = working_hours_service.worked_seconds_for_week(
            scope, employee.id, date(2026, 1, 5), week_start_day=0
        )
        assert seconds == 5 * 8 * 3600

    def test_mismatched_week_start_day_raises_validation_error(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        scope = _scope("admin", org.id, user_id=admin.id)
        with pytest.raises(ValidationError):
            # 2026-01-05 is a Monday (weekday 0), not a Sunday (6).
            working_hours_service.worked_seconds_for_week(
                scope, employee.id, date(2026, 1, 5), week_start_day=6
            )


class TestScheduledVsWorked:
    def test_returns_scheduled_worked_and_difference(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")

        make_shift(
            db_session,
            organization=org,
            department=department,
            employee=employee,
            created_by=admin,
            starts_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 5),
            status="published",
            published_at=datetime.now(timezone.utc),
        )
        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 5),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        result = working_hours_service.scheduled_vs_worked(
            scope, employee.id, date(2026, 1, 5)
        )

        assert result["scheduled_hours"] == Decimal("8")
        assert result["worked_hours"] == Decimal("9")
        assert result["difference_hours"] == Decimal("1")

    def test_draft_shifts_are_not_counted_as_scheduled(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")

        make_shift(
            db_session,
            organization=org,
            department=department,
            employee=employee,
            created_by=admin,
            starts_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
            business_date=date(2026, 1, 5),
            status="draft",
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        result = working_hours_service.scheduled_vs_worked(
            scope, employee.id, date(2026, 1, 5)
        )
        assert result["scheduled_hours"] == Decimal("0")
        assert result["worked_hours"] == Decimal("0")
        assert result["difference_hours"] == Decimal("0")


class TestDaylightSavingTransition:
    """business_date_for/worked_seconds_for_day for real DST transitions in
    America/New_York (2026-03-08 springs forward 2:00am -> 3:00am, a 23-
    wall-clock-hour day but only 22 real hours long; 2026-11-01 falls
    back 2:00am -> 1:00am, a 25-wall-clock-hour day but 24 real hours
    long). Both still attribute to a single, well-defined local calendar
    date, and worked_seconds_for_day's duration math needs no special
    casing for either — the DB always stores/returns absolute instants,
    so (ended_at - started_at) is correct regardless of any local DST
    shift in between.

    Local datetimes here are converted to UTC before being handed to the
    factory (mirroring what actually reaches Postgres) rather than
    subtracted directly in Python: subtracting two ``zoneinfo``-aware
    datetimes that share the same tzinfo object across a DST boundary
    is a well-known CPython pitfall (it uses a naive wall-clock
    subtraction instead of each side's own correctly-computed UTC
    offset), which would silently produce the wrong "expected" value
    for this test if used carelessly.
    """

    NY = ZoneInfo("America/New_York")

    def test_business_date_for_is_continuous_across_the_spring_forward_gap(self):
        # 06:59 UTC = 01:59 EST (just before the 2am->3am jump); 07:00 UTC
        # = 03:00 EDT (the instant right after it). Both must attribute to
        # the same local calendar date -- no date skipped or double
        # counted at the gap itself.
        just_before = datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)
        just_after = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
        assert business_date_for(just_before, self.NY) == date(2026, 3, 8)
        assert business_date_for(just_after, self.NY) == date(2026, 3, 8)

    def test_spring_forward_day_is_22_real_hours_but_attributes_normally(
        self, db_session
    ):
        org = make_organization(db_session, timezone="America/New_York")
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        started_at = datetime(2026, 3, 8, 0, 30, tzinfo=self.NY)
        ended_at = datetime(2026, 3, 8, 23, 30, tzinfo=self.NY)
        assert business_date_for(started_at, self.NY) == date(2026, 3, 8)

        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=started_at.astimezone(timezone.utc),
            ended_at=ended_at.astimezone(timezone.utc),
            business_date=date(2026, 3, 8),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 3, 8)
        )
        assert seconds == 22 * 3600

    def test_fall_back_day_is_24_real_hours_but_attributes_normally(self, db_session):
        org = make_organization(db_session, timezone="America/New_York")
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")

        started_at = datetime(2026, 11, 1, 0, 30, tzinfo=self.NY)
        ended_at = datetime(2026, 11, 1, 23, 30, tzinfo=self.NY)
        assert business_date_for(started_at, self.NY) == date(2026, 11, 1)

        make_attendance_entry(
            db_session,
            organization=org,
            employee=employee,
            created_by=admin,
            started_at=started_at.astimezone(timezone.utc),
            ended_at=ended_at.astimezone(timezone.utc),
            business_date=date(2026, 11, 1),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        seconds = working_hours_service.worked_seconds_for_day(
            scope, employee.id, date(2026, 11, 1)
        )
        assert seconds == 24 * 3600

    def test_scheduled_hours_across_the_spring_forward_gap_are_22_real_hours(
        self, db_session
    ):
        """DST-transition coverage for *scheduled* hours (a Shift's
        duration), mirroring
        test_spring_forward_day_is_22_real_hours_but_attributes_normally's
        rationale for *worked* hours above: working_hours.scheduled_vs_worked
        (via its private _scheduled_seconds helper) computes a shift's
        duration the same way -- (ends_at - starts_at).total_seconds() on
        two absolute UTC instants -- so it needs no DST special-casing
        either, but that needs its own test since only the worked-hours
        side had one before this fix.
        """
        org = make_organization(db_session, timezone="America/New_York")
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")

        # A shift spanning the entire spring-forward day: 00:30 EST
        # (before the 2am -> 3am jump) to 23:30 EDT (after it) -- 23
        # wall-clock hours, but only 22 real hours long.
        starts_at = datetime(2026, 3, 8, 0, 30, tzinfo=self.NY)
        ends_at = datetime(2026, 3, 8, 23, 30, tzinfo=self.NY)
        assert business_date_for(starts_at, self.NY) == date(2026, 3, 8)

        make_shift(
            db_session,
            organization=org,
            department=department,
            employee=employee,
            created_by=admin,
            starts_at=starts_at.astimezone(timezone.utc),
            ends_at=ends_at.astimezone(timezone.utc),
            business_date=date(2026, 3, 8),
            status="published",
            published_at=datetime.now(timezone.utc),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        result = working_hours_service.scheduled_vs_worked(
            scope, employee.id, date(2026, 3, 8)
        )
        assert result["scheduled_hours"] == Decimal("22")

    def test_scheduled_hours_across_the_fall_back_gap_are_24_real_hours(
        self, db_session
    ):
        org = make_organization(db_session, timezone="America/New_York")
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")

        # A shift spanning the entire fall-back day: 25 wall-clock hours,
        # but only 24 real hours long.
        starts_at = datetime(2026, 11, 1, 0, 30, tzinfo=self.NY)
        ends_at = datetime(2026, 11, 1, 23, 30, tzinfo=self.NY)
        assert business_date_for(starts_at, self.NY) == date(2026, 11, 1)

        make_shift(
            db_session,
            organization=org,
            department=department,
            employee=employee,
            created_by=admin,
            starts_at=starts_at.astimezone(timezone.utc),
            ends_at=ends_at.astimezone(timezone.utc),
            business_date=date(2026, 11, 1),
            status="published",
            published_at=datetime.now(timezone.utc),
        )

        scope = _scope("admin", org.id, user_id=admin.id)
        result = working_hours_service.scheduled_vs_worked(
            scope, employee.id, date(2026, 11, 1)
        )
        assert result["scheduled_hours"] == Decimal("24")
