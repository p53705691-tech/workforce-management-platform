"""Flask CLI commands for maintenance operations.

Registered on the app in ``create_app`` (see ``app/__init__.py``), same
place every blueprint gets registered. These are operator-invoked
maintenance tasks, not user-facing routes, so they live outside
``app/routes``.
"""

import os
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import secrets

import click
from flask import Flask
from sqlalchemy import insert

from app.auth.passwords import hash_password
from app.extensions import db
from app.models.attendance_entry import AttendanceEntry
from app.models.department import Department
from app.models.department_manager import DepartmentManager
from app.models.employee import Employee
from app.models.employee_pay_rate import EmployeePayRate
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.organization import Organization
from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier
from app.models.shift import Shift
from app.models.user import User
from app.services import attendance as attendance_service

# Seed data is environment data, not schema (per CLAUDE.md's architecture
# plan), so the confirmed default policy is created here via a CLI
# command rather than baked into a migration. Fixed epoch, well before
# any real organization's data, so a newly seeded policy covers every
# historical attendance record without needing a per-organization
# "creation date" lookup.
_SEED_POLICY_EFFECTIVE_FROM = date(2020, 1, 1)

# Fixed (not randomized) login password for every account `seed
# benchmark` creates -- deliberately different from `seed demo-scenario`
# above, which randomizes and never persists its password. A benchmark
# organization exists purely as disposable load-test fixture data
# (refuses to run in production, same as demo-scenario) that
# scripts/benchmark_dashboard.py and scripts/load_test.py both need to
# log into non-interactively and repeatably across separate process
# invocations, with no human in the loop to copy a freshly generated
# secret out of this command's output first. Never used for anything
# that could contain real people or real credentials.
_BENCHMARK_PASSWORD = "Benchmark-Seed-Only-2026!"


def register_cli(app: Flask) -> None:
    @app.cli.group("attendance")
    def attendance_group():
        """Attendance maintenance commands."""

    @attendance_group.command("flag-stale")
    @click.option(
        "--cutoff-hours",
        default=16,
        show_default=True,
        type=int,
        help="Hours since clock-in after which an open entry with no "
        "clock-out is flagged for review (confirmed rule A11).",
    )
    def flag_stale(cutoff_hours: int) -> None:
        """Mark stale open attendance entries as needs_review.

        Intended to run periodically (e.g. via cron) rather than needing
        a background scheduler in the MVP.
        """
        count = attendance_service.flag_stale_open_entries(cutoff_hours=cutoff_hours)
        entry_word = "entry" if count == 1 else "entries"
        click.echo(f"Flagged {count} stale open attendance {entry_word} for review.")

    @app.cli.group("seed")
    def seed_group():
        """One-off environment data seeding commands."""

    @seed_group.command("overtime-policy")
    @click.option(
        "--organization",
        "organization_slug",
        required=True,
        help="Slug of the organization to seed a default overtime policy for.",
    )
    def seed_overtime_policy(organization_slug: str) -> None:
        """Seed the confirmed default overtime policy for one organization.

        8h daily / 40h weekly thresholds; daily tiers 0-2h beyond
        threshold at 1.5x and 2h+ at 2.0x; weekly tier beyond threshold
        at 1.5x. Refuses to run if the organization already has any
        overtime policy — reconfiguring an existing policy is a real
        effective-dated business change, not something this one-shot
        seed command should guess at.
        """
        organization = (
            db.session.query(Organization)
            .filter(Organization.slug == organization_slug)
            .first()
        )
        if organization is None:
            raise click.ClickException(
                f"No organization found with slug {organization_slug!r}."
            )

        existing_policy = (
            db.session.query(OvertimePolicy)
            .filter(OvertimePolicy.organization_id == organization.id)
            .first()
        )
        if existing_policy is not None:
            raise click.ClickException(
                f"Organization {organization_slug!r} already has an "
                "overtime policy; this seed command only applies to "
                "unconfigured organizations."
            )

        policy = OvertimePolicy(
            organization_id=organization.id,
            name="Default Overtime Policy",
            daily_threshold_hours=Decimal("8.00"),
            weekly_threshold_hours=Decimal("40.00"),
            week_start_day=0,
            effective_from=_SEED_POLICY_EFFECTIVE_FROM,
            effective_to=None,
        )
        db.session.add(policy)
        db.session.flush()

        db.session.add_all(
            [
                OvertimeTier(
                    policy_id=policy.id,
                    scope="daily",
                    tier_order=0,
                    from_hours=Decimal("0.00"),
                    to_hours=Decimal("2.00"),
                    multiplier=Decimal("1.50"),
                ),
                OvertimeTier(
                    policy_id=policy.id,
                    scope="daily",
                    tier_order=1,
                    from_hours=Decimal("2.00"),
                    to_hours=None,
                    multiplier=Decimal("2.00"),
                ),
                OvertimeTier(
                    policy_id=policy.id,
                    scope="weekly",
                    tier_order=0,
                    from_hours=Decimal("0.00"),
                    to_hours=None,
                    multiplier=Decimal("1.50"),
                ),
            ]
        )
        db.session.commit()
        click.echo(
            f"Seeded default overtime policy for organization {organization_slug!r}."
        )

    @seed_group.command("demo-scenario")
    @click.option(
        "--organization",
        "organization_slug",
        required=True,
        help="Slug of the organization to seed a multi-employee demo scenario into.",
    )
    def seed_demo_scenario(organization_slug: str) -> None:
        """Seed a realistic multi-department, multi-employee scenario for
        manual review: departments, employees, login users, an overtime
        policy, a published week of shifts, a history of attendance
        (on-time, late, a stale needs-review entry, currently-working,
        absent, on leave), and a few leave requests in different states.

        Additive on top of whatever the organization already has (an
        existing employee's Tuesday shift, for example, is reused rather
        than duplicated — shifts and attendance entries both reject
        overlapping ranges for the same employee at the database level).
        Refuses to run twice: once the Warehouse department exists, this
        organization is considered already seeded.

        Refuses to run at all against a production configuration
        (security review finding): this command provisions several
        manager-role login accounts and deletes real attendance rows
        (see the stray-entry cleanup below), and its only guard against
        the wrong organization is "does not have a Warehouse department
        yet" — not "is this actually a demo org".

        Checked against the ``FLASK_ENV`` environment variable directly
        (the same one ``create_app`` itself reads), not
        ``current_app.debug``/``.testing``: Flask's own CLI machinery
        (``ScriptInfo.load_app``) unconditionally overwrites ``app.debug``
        (and therefore ``app.config['DEBUG']``) from the unrelated
        ``FLASK_DEBUG`` variable whenever the app is loaded via the real
        ``flask`` command — which is how this command is actually
        invoked in practice — so checking ``current_app.debug`` here
        would read ``False`` even when ``FLASK_ENV=development`` and
        silently block every real invocation.
        """
        if os.environ.get("FLASK_ENV", "development") == "production":
            raise click.ClickException(
                "This command seeds demo accounts with a shared password "
                "and deletes short attendance entries for the target "
                "organization; it refuses to run against a production "
                "configuration (FLASK_ENV=production)."
            )

        organization = (
            db.session.query(Organization)
            .filter(Organization.slug == organization_slug)
            .first()
        )
        if organization is None:
            raise click.ClickException(
                f"No organization found with slug {organization_slug!r}."
            )

        if (
            db.session.query(Department)
            .filter(Department.organization_id == organization.id, Department.code == "WH")
            .first()
            is not None
        ):
            raise click.ClickException(
                f"Organization {organization_slug!r} already has a Warehouse "
                "department; this command only seeds an unseeded demo org."
            )

        admin_user = (
            db.session.query(User)
            .filter(User.organization_id == organization.id, User.role == "admin")
            .first()
        )
        if admin_user is None:
            raise click.ClickException(
                f"Organization {organization_slug!r} has no admin user yet; "
                "create one before seeding a demo scenario."
            )

        # Generated per run, not a fixed literal (security review
        # finding): printed once below so an operator can actually use
        # it, never persisted or logged anywhere else.
        demo_password = secrets.token_urlsafe(12)
        demo_password_hash = hash_password(demo_password)

        # Earlier manual UI testing left a few seconds-long clock-in/out
        # entries for today on this organization's first employee (real
        # rows, but with no scenario value and short enough to collide
        # with the full-day entry seeded for them below); clear those out
        # so today's data tells one coherent story. Scoped to only the
        # specific pre-existing employees this scenario reuses (never a
        # blanket "every short entry in the org today"), so this can
        # never delete an unrelated employee's real attendance record.
        for stray_entry in (
            db.session.query(AttendanceEntry)
            .join(Employee, Employee.id == AttendanceEntry.employee_id)
            .filter(
                AttendanceEntry.organization_id == organization.id,
                AttendanceEntry.business_date == date.today(),
                AttendanceEntry.status == "closed",
                Employee.employee_number.in_(("EMP001", "EMP-1002")),
            )
            .all()
        ):
            if stray_entry.ended_at - stray_entry.started_at < timedelta(minutes=5):
                db.session.delete(stray_entry)

        # --- departments -----------------------------------------------
        operations = (
            db.session.query(Department)
            .filter(Department.organization_id == organization.id, Department.code == "OPS")
            .first()
        )
        if operations is None:
            raise click.ClickException(
                f"Organization {organization_slug!r} has no 'OPS' department "
                "yet; this command assumes one already exists."
            )

        new_departments = {}
        for name, code in [
            ("Warehouse", "WH"),
            ("Customer Support", "CS"),
            ("Sales", "SALES"),
        ]:
            department = Department(organization_id=organization.id, name=name, code=code)
            db.session.add(department)
            new_departments[code] = department
        db.session.flush()
        departments = {"OPS": operations, **new_departments}

        existing_manager_user = (
            db.session.query(User)
            .filter(User.organization_id == organization.id, User.role == "manager")
            .first()
        )
        if existing_manager_user is not None:
            db.session.add(
                DepartmentManager(
                    user_id=existing_manager_user.id,
                    department_id=operations.id,
                    organization_id=organization.id,
                )
            )

        # --- employees ---------------------------------------------------
        # (number, first, last, dept code, hired_on, hourly rate, login role)
        new_employee_seed = [
            ("EMP-3001", "Taylor", "Brooks", "OPS", date(2023, 3, 10), Decimal("24.50"), "employee"),
            ("EMP-3002", "Morgan", "Diaz", "OPS", date(2024, 6, 1), Decimal("21.00"), "employee"),
            ("EMP-3003", "Casey", "Nguyen", "WH", date(2022, 11, 15), Decimal("29.00"), "manager"),
            ("EMP-3004", "Riley", "Thompson", "WH", date(2023, 8, 1), Decimal("20.50"), "employee"),
            ("EMP-3005", "Jamie", "Patel", "WH", date(2024, 2, 20), Decimal("19.75"), "employee"),
            ("EMP-3006", "Avery", "Kim", "CS", date(2021, 5, 5), Decimal("27.00"), "manager"),
            ("EMP-3007", "Drew", "Sanchez", "CS", date(2023, 1, 12), Decimal("22.25"), "employee"),
            ("EMP-3008", "Quinn", "Walker", "CS", date(2024, 9, 9), Decimal("18.50"), "employee"),
            ("EMP-3009", "Peyton", "Reed", "SALES", date(2022, 7, 19), Decimal("31.00"), "manager"),
            ("EMP-3010", "Harper", "Collins", "SALES", date(2025, 1, 6), Decimal("23.00"), "employee"),
        ]

        employees = {}
        for existing_number in ("EMP001", "EMP-1002"):
            employee = (
                db.session.query(Employee)
                .filter(
                    Employee.organization_id == organization.id,
                    Employee.employee_number == existing_number,
                )
                .first()
            )
            if employee is not None:
                employees[existing_number] = employee

        for number, first, last, dept_code, hired_on, rate, login_role in new_employee_seed:
            employee = Employee(
                organization_id=organization.id,
                department_id=departments[dept_code].id,
                employee_number=number,
                first_name=first,
                last_name=last,
                employment_status="active",
                hired_on=hired_on,
            )
            db.session.add(employee)
            employees[number] = employee
        db.session.flush()

        # Sam Rivera (EMP-1002) already exists but has no login user or pay
        # rate yet; give her both here alongside the rest of the scenario.
        if "EMP-1002" in employees:
            new_employee_seed.append(
                ("EMP-1002", "Sam", "Rivera", "OPS", employees["EMP-1002"].hired_on, Decimal("22.00"), "employee")
            )

        for number, first, last, dept_code, hired_on, rate, login_role in new_employee_seed:
            employee = employees[number]
            if (
                db.session.query(EmployeePayRate)
                .filter(EmployeePayRate.employee_id == employee.id)
                .first()
                is None
            ):
                db.session.add(
                    EmployeePayRate(
                        employee_id=employee.id,
                        organization_id=organization.id,
                        hourly_rate=rate,
                        effective_from=hired_on,
                        effective_to=None,
                    )
                )
            db.session.add(
                User(
                    organization_id=organization.id,
                    employee_id=employee.id,
                    # Scoped by organization slug, not a bare "@demo.local":
                    # users.email is unique across the whole table (not
                    # per-organization), and every field here (including
                    # the ten first/last names in new_employee_seed above)
                    # is a hardcoded constant — so a bare "@demo.local"
                    # address guarantees a collision the moment this
                    # command is run for a *second* organization.
                    email=f"{first.lower()}.{last.lower()}@{organization_slug}.demo.local",
                    password_hash=demo_password_hash,
                    role=login_role,
                )
            )
        db.session.flush()

        managers_by_dept_code = {"WH": "EMP-3003", "CS": "EMP-3006", "SALES": "EMP-3009"}
        for dept_code, employee_number in managers_by_dept_code.items():
            manager_user = (
                db.session.query(User)
                .filter(User.employee_id == employees[employee_number].id)
                .first()
            )
            db.session.add(
                DepartmentManager(
                    user_id=manager_user.id,
                    department_id=departments[dept_code].id,
                    organization_id=organization.id,
                )
            )

        # --- overtime policy ---------------------------------------------
        if (
            db.session.query(OvertimePolicy)
            .filter(OvertimePolicy.organization_id == organization.id)
            .first()
            is None
        ):
            policy = OvertimePolicy(
                organization_id=organization.id,
                name="Default Overtime Policy",
                daily_threshold_hours=Decimal("8.00"),
                weekly_threshold_hours=Decimal("40.00"),
                week_start_day=0,
                effective_from=_SEED_POLICY_EFFECTIVE_FROM,
                effective_to=None,
            )
            db.session.add(policy)
            db.session.flush()
            db.session.add_all(
                [
                    OvertimeTier(
                        policy_id=policy.id, scope="daily", tier_order=0,
                        from_hours=Decimal("0.00"), to_hours=Decimal("2.00"),
                        multiplier=Decimal("1.50"),
                    ),
                    OvertimeTier(
                        policy_id=policy.id, scope="daily", tier_order=1,
                        from_hours=Decimal("2.00"), to_hours=None,
                        multiplier=Decimal("2.00"),
                    ),
                    OvertimeTier(
                        policy_id=policy.id, scope="weekly", tier_order=0,
                        from_hours=Decimal("0.00"), to_hours=None,
                        multiplier=Decimal("1.50"),
                    ),
                ]
            )

        # --- schedule + attendance for the current work week --------------
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        weekday_dates = {
            "mon": monday, "tue": monday + timedelta(days=1), "wed": monday + timedelta(days=2),
            "thu": monday + timedelta(days=3), "fri": monday + timedelta(days=4),
        }
        now = datetime.now(timezone.utc)
        published_at = datetime.combine(monday - timedelta(days=3), time(9, 0), tzinfo=timezone.utc)

        # (start_hour, end_hour) per employee number, applied Mon/Tue/Thu/Fri.
        base_shift_hours = {
            "EMP001": (8, 16), "EMP-1002": (12, 20),
            "EMP-3001": (8, 16), "EMP-3002": (8, 16), "EMP-3003": (7, 15),
            "EMP-3004": (7, 15), "EMP-3005": (15, 23), "EMP-3006": (9, 17),
            "EMP-3007": (9, 17), "EMP-3008": (13, 21), "EMP-3009": (9, 17),
            "EMP-3010": (9, 17),
        }
        # Riley swings to the afternoon shift today, so she's still clocked
        # in when this command is typically run for review (see "now" above).
        wed_override_hours = {"EMP-3004": (12, 20)}
        # No shift at all: Morgan is on approved leave Wed/Thu; Jamie is
        # locked out of clocking in again after her Monday needs_review
        # entry below (an employee may only have one open/needs_review
        # entry at a time, per uq_attendance_entries_employee_id_open) and
        # her manager hasn't corrected it yet; Jordan already has a
        # published Tuesday shift from earlier manual testing, reused
        # below instead of duplicated.
        skip_shift = {
            ("EMP-3002", "wed"), ("EMP-3002", "thu"),
            ("EMP-3005", "tue"), ("EMP-3005", "wed"), ("EMP-3005", "thu"), ("EMP-3005", "fri"),
            ("EMP001", "tue"),
        }
        # No attendance entry created despite a published shift today:
        # Harper is the day's "absent" example.
        skip_attendance_today = {"EMP-3010"}
        late_minutes_by_employee_weekday = {("EMP-3001", "mon"): 14, ("EMP-3007", "tue"): 22}
        needs_review_employee_weekday = {("EMP-3005", "mon")}

        employee_dept_code = {number: dept for number, _, _, dept, *_ in new_employee_seed}
        employee_dept_code["EMP001"] = "OPS"
        user_id_by_employee_number = {
            number: db.session.query(User).filter(User.employee_id == employees[number].id).first().id
            for number in employees
        }

        jordan_tuesday_shift = (
            db.session.query(Shift)
            .filter(Shift.employee_id == employees["EMP001"].id, Shift.business_date == weekday_dates["tue"])
            .first()
        )

        for weekday_key, business_date in weekday_dates.items():
            for number, (start_hour, end_hour) in base_shift_hours.items():
                employee = employees[number]
                key = (number, weekday_key)

                if key in skip_shift:
                    shift = jordan_tuesday_shift if key == ("EMP001", "tue") else None
                    if shift is None:
                        continue
                else:
                    start_hour, end_hour = (
                        wed_override_hours.get(number, (start_hour, end_hour))
                        if weekday_key == "wed"
                        else (start_hour, end_hour)
                    )
                    starts_at = datetime.combine(business_date, time(start_hour, 0), tzinfo=timezone.utc)
                    ends_at = datetime.combine(business_date, time(end_hour, 0), tzinfo=timezone.utc)
                    shift = Shift(
                        organization_id=organization.id,
                        department_id=departments[employee_dept_code[number]].id,
                        employee_id=employee.id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        business_date=business_date,
                        break_minutes=30,
                        status="published",
                        published_at=published_at,
                        created_by_user_id=admin_user.id,
                    )
                    db.session.add(shift)
                    db.session.flush()

                if business_date > today:
                    continue  # future shift: no attendance yet

                if key in needs_review_employee_weekday:
                    db.session.add(
                        AttendanceEntry(
                            organization_id=organization.id,
                            employee_id=employee.id,
                            shift_id=shift.id,
                            started_at=shift.starts_at,
                            ended_at=None,
                            business_date=business_date,
                            break_minutes=0,
                            status="needs_review",
                            source="web",
                            created_by_user_id=user_id_by_employee_number[number],
                        )
                    )
                    continue

                if business_date == today:
                    if number in skip_attendance_today or now < shift.starts_at:
                        continue
                    if now >= shift.ends_at:
                        db.session.add(
                            AttendanceEntry(
                                organization_id=organization.id, employee_id=employee.id,
                                shift_id=shift.id, started_at=shift.starts_at, ended_at=shift.ends_at,
                                business_date=business_date, break_minutes=30, status="closed",
                                source="web", created_by_user_id=user_id_by_employee_number[number],
                            )
                        )
                    else:
                        db.session.add(
                            AttendanceEntry(
                                organization_id=organization.id, employee_id=employee.id,
                                shift_id=shift.id, started_at=shift.starts_at, ended_at=None,
                                business_date=business_date, break_minutes=0, status="open",
                                source="web", created_by_user_id=user_id_by_employee_number[number],
                            )
                        )
                    continue

                late = late_minutes_by_employee_weekday.get((number, weekday_key), 0)
                db.session.add(
                    AttendanceEntry(
                        organization_id=organization.id, employee_id=employee.id, shift_id=shift.id,
                        started_at=shift.starts_at + timedelta(minutes=late), ended_at=shift.ends_at,
                        business_date=business_date, break_minutes=30, status="closed",
                        source="web", created_by_user_id=user_id_by_employee_number[number],
                    )
                )

        # --- leave requests -------------------------------------------------
        vacation = LeaveType(
            organization_id=organization.id, code="VAC", name="Vacation",
            is_paid=True, requires_approval=True, blocks_scheduling=True, is_active=True,
        )
        sick = LeaveType(
            organization_id=organization.id, code="SICK", name="Sick Leave",
            is_paid=True, requires_approval=True, blocks_scheduling=True, is_active=True,
        )
        unpaid = LeaveType(
            organization_id=organization.id, code="UNPAID", name="Unpaid Leave",
            is_paid=False, requires_approval=True, blocks_scheduling=True, is_active=True,
        )
        db.session.add_all([vacation, sick, unpaid])
        db.session.flush()

        morgan_id = employees["EMP-3002"].id
        riley_id = employees["EMP-3004"].id
        quinn_id = employees["EMP-3008"].id
        db.session.add_all(
            [
                LeaveRequest(
                    organization_id=organization.id, employee_id=morgan_id, leave_type_id=vacation.id,
                    starts_at=datetime.combine(weekday_dates["wed"], time.min, tzinfo=timezone.utc),
                    ends_at=datetime.combine(weekday_dates["fri"], time.min, tzinfo=timezone.utc),
                    status="approved", reason="Family trip",
                    requested_by_user_id=user_id_by_employee_number["EMP-3002"],
                    decided_by_user_id=admin_user.id,
                    decided_at=published_at,
                ),
                LeaveRequest(
                    organization_id=organization.id, employee_id=riley_id, leave_type_id=vacation.id,
                    starts_at=datetime.combine(monday + timedelta(days=21), time.min, tzinfo=timezone.utc),
                    ends_at=datetime.combine(monday + timedelta(days=23), time.min, tzinfo=timezone.utc),
                    status="pending", reason="Long weekend",
                    requested_by_user_id=user_id_by_employee_number["EMP-3004"],
                ),
                LeaveRequest(
                    organization_id=organization.id, employee_id=quinn_id, leave_type_id=sick.id,
                    starts_at=datetime.combine(monday - timedelta(days=10), time.min, tzinfo=timezone.utc),
                    ends_at=datetime.combine(monday - timedelta(days=9), time.min, tzinfo=timezone.utc),
                    status="rejected", reason="Feeling unwell",
                    requested_by_user_id=user_id_by_employee_number["EMP-3008"],
                    decided_by_user_id=user_id_by_employee_number["EMP-3006"],
                    decided_at=datetime.combine(monday - timedelta(days=9), time(9, 0), tzinfo=timezone.utc),
                    decision_note="Submitted after the leave period already passed.",
                ),
            ]
        )

        db.session.commit()
        click.echo(
            f"Seeded demo scenario for organization {organization_slug!r}: "
            f"{len(new_employee_seed)} employees added across "
            f"{len(new_departments)} new departments. All new logins use "
            f"password {demo_password!r} (shown once here only)."
        )

    # Department names/codes used by `seed benchmark` below -- a fixed
    # roster of 6 (within the confirmed 5-8 "realistic department count"
    # range for this seed) so every benchmark org, regardless of
    # --employees, has the same department shape and the query-count
    # benchmark script (scripts/benchmark_dashboard.py) is comparing like
    # with like across sizes.
    _BENCHMARK_DEPARTMENTS = [
        ("Operations", "OPS"),
        ("Warehouse", "WH"),
        ("Customer Support", "CS"),
        ("Sales", "SALES"),
        ("Logistics", "LOG"),
        ("Maintenance", "MAINT"),
    ]

    # (start_hour, duration_hours, break_minutes) cycled across employees
    # by index, so the seeded organization has a realistic mix of shift
    # shapes -- including one overnight shift (22:00 -> 06:00 the next
    # day, per app.models.shift's "one row per shift, even overnight"
    # convention) and one shorter part-time shift -- rather than every
    # employee sharing identical hours.
    _BENCHMARK_SHIFT_TEMPLATES = [
        (8, 8, 30),
        (9, 8, 30),
        (14, 8, 30),
        (22, 8, 30),
        (6, 6, 15),
    ]

    _BENCHMARK_FIRST_NAMES = [
        "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery",
        "Drew", "Quinn", "Peyton", "Harper", "Rowan", "Skyler", "Reese", "Cameron",
    ]
    _BENCHMARK_LAST_NAMES = [
        "Nguyen", "Brooks", "Diaz", "Thompson", "Patel", "Kim", "Sanchez", "Walker",
        "Reed", "Collins", "Bailey", "Foster", "Hayes", "Coleman", "Price", "Ward",
    ]

    @seed_group.command("benchmark")
    @click.option(
        "--organization",
        "organization_slug",
        required=True,
        help="Slug of the organization to seed. Created fresh if it does "
        "not exist yet; refuses to run against an organization that "
        "already has any departments or employees, so each size gets "
        "its own dedicated organization (e.g. bench-10, bench-50, ...).",
    )
    @click.option(
        "--employees",
        "employee_count",
        required=True,
        type=click.IntRange(1, 2000),
        help="Number of employees to bulk-create, spread across a fixed "
        "roster of 6 departments.",
    )
    @click.option(
        "--days",
        "days",
        default=60,
        show_default=True,
        type=click.IntRange(1, 365),
        help="Number of trailing days (including today) of published "
        "shifts and matching attendance history to generate per employee.",
    )
    def seed_benchmark(organization_slug: str, employee_count: int, days: int) -> None:
        """Bulk-insert a large, realistic organization for query-count and
        latency benchmarking (``scripts/benchmark_dashboard.py``,
        ``scripts/load_test.py``) -- up to hundreds of employees with real
        shift/attendance/pay-rate/leave history, fast.

        Deliberately not built on ``tests/factories.py`` or
        ``seed-demo-scenario``'s one-row-at-a-time ORM object pattern:
        this needs to seed up to ~500 employees x tens of days of history
        (tens of thousands of shift/attendance rows) in one command
        invocation, so employees/shifts/attendance/pay-rates are all
        inserted via ``sqlalchemy.insert(Model)`` executed once per table
        against a list of plain dicts (SQLAlchemy 2.0's "insertmanyvalues"
        batching, not one INSERT per row) rather than constructing and
        adding one ORM object per row.

        Every attendance entry is generated with ``shift_id=None`` even
        though a matching published shift exists for the same employee
        and day: real shift-matching (``attendance._match_shift``) is a
        clock-in-time service concern this bulk path deliberately
        bypasses for speed, and none of the reports this benchmarks
        (dashboard counts, ``working_hours``, ``labor_cost``,
        ``reports.overtime_summary``/``hours_trend``) join attendance to
        shifts -- only the attendance list's optional "late" display does,
        which simply shows nothing extra for these rows.

        Refuses to run against a production configuration, same
        FLASK_ENV check and rationale as ``seed demo-scenario`` above
        (provisions shared-password login accounts).
        """
        if os.environ.get("FLASK_ENV", "development") == "production":
            raise click.ClickException(
                "This command seeds bulk benchmark data and demo accounts "
                "with a shared password; it refuses to run against a "
                "production configuration (FLASK_ENV=production)."
            )

        organization = (
            db.session.query(Organization)
            .filter(Organization.slug == organization_slug)
            .first()
        )
        if organization is None:
            organization = Organization(
                name=f"Benchmark Org ({organization_slug})",
                slug=organization_slug,
                timezone="UTC",
                currency_code="USD",
            )
            db.session.add(organization)
            db.session.flush()

        already_seeded = (
            db.session.query(Department.id)
            .filter(Department.organization_id == organization.id)
            .first()
            is not None
        ) or (
            db.session.query(Employee.id)
            .filter(Employee.organization_id == organization.id)
            .first()
            is not None
        )
        if already_seeded:
            raise click.ClickException(
                f"Organization {organization_slug!r} already has departments "
                "or employees; this command only seeds a fresh organization "
                "(use a dedicated slug per benchmark size, e.g. bench-10, "
                "bench-50, bench-100, bench-250, bench-500)."
            )

        rng = random.Random(f"benchmark-seed:{organization_slug}")

        demo_password_hash = hash_password(_BENCHMARK_PASSWORD)

        admin_user = User(
            organization_id=organization.id,
            employee_id=None,
            email=f"admin@{organization_slug}.bench.local",
            password_hash=demo_password_hash,
            role="admin",
        )
        db.session.add(admin_user)
        db.session.flush()

        # --- departments -------------------------------------------------
        departments = []
        for name, code in _BENCHMARK_DEPARTMENTS:
            department = Department(organization_id=organization.id, name=name, code=code)
            db.session.add(department)
            departments.append(department)
        db.session.flush()

        manager_users = []
        for department in departments:
            manager_user = User(
                organization_id=organization.id,
                employee_id=None,
                email=f"manager.{department.code.lower()}@{organization_slug}.bench.local",
                password_hash=demo_password_hash,
                role="manager",
            )
            db.session.add(manager_user)
            manager_users.append(manager_user)
        db.session.flush()
        for department, manager_user in zip(departments, manager_users):
            db.session.add(
                DepartmentManager(
                    user_id=manager_user.id,
                    department_id=department.id,
                    organization_id=organization.id,
                )
            )

        # --- overtime policy ----------------------------------------------
        policy = OvertimePolicy(
            organization_id=organization.id,
            name="Default Overtime Policy",
            daily_threshold_hours=Decimal("8.00"),
            weekly_threshold_hours=Decimal("40.00"),
            week_start_day=0,
            effective_from=_SEED_POLICY_EFFECTIVE_FROM,
            effective_to=None,
        )
        db.session.add(policy)
        db.session.flush()
        db.session.add_all(
            [
                OvertimeTier(
                    policy_id=policy.id, scope="daily", tier_order=0,
                    from_hours=Decimal("0.00"), to_hours=Decimal("2.00"),
                    multiplier=Decimal("1.50"),
                ),
                OvertimeTier(
                    policy_id=policy.id, scope="daily", tier_order=1,
                    from_hours=Decimal("2.00"), to_hours=None,
                    multiplier=Decimal("2.00"),
                ),
                OvertimeTier(
                    policy_id=policy.id, scope="weekly", tier_order=0,
                    from_hours=Decimal("0.00"), to_hours=None,
                    multiplier=Decimal("1.50"),
                ),
            ]
        )

        # --- employees (bulk insert) ---------------------------------------
        today = date.today()
        hired_on = today - timedelta(days=days + 365)
        employee_number_width = max(6, len(str(employee_count)))
        employee_rows = []
        for i in range(employee_count):
            department = departments[i % len(departments)]
            first_name = _BENCHMARK_FIRST_NAMES[i % len(_BENCHMARK_FIRST_NAMES)]
            last_name = _BENCHMARK_LAST_NAMES[(i // len(_BENCHMARK_FIRST_NAMES)) % len(_BENCHMARK_LAST_NAMES)]
            employee_rows.append(
                {
                    "organization_id": organization.id,
                    "department_id": department.id,
                    "employee_number": f"BENCH-{i + 1:0{employee_number_width}d}",
                    "first_name": first_name,
                    "last_name": f"{last_name}-{i + 1}",
                    "employment_status": "active",
                    "hired_on": hired_on,
                }
            )
        db.session.execute(insert(Employee), employee_rows)
        db.session.flush()

        # Read the newly inserted rows back rather than trusting bulk
        # insert result-row order: employee_number is a zero-padded,
        # strictly increasing sequence, so ordering by it reconstructs
        # the exact same per-employee order used to build employee_rows
        # above, needed to line up department_id/pay-rate/shift-template
        # assignment below without any fragile RETURNING-order assumption.
        employees = (
            db.session.query(Employee.id, Employee.department_id)
            .filter(
                Employee.organization_id == organization.id,
                Employee.employee_number.like("BENCH-%"),
            )
            .order_by(Employee.employee_number)
            .all()
        )

        # Give a handful of employees a real login (one employee-role
        # account is enough for scripts/benchmark_dashboard.py and
        # scripts/load_test.py to exercise the Employee Dashboard).
        if employees:
            db.session.add(
                User(
                    organization_id=organization.id,
                    employee_id=employees[0].id,
                    email=f"employee@{organization_slug}.bench.local",
                    password_hash=demo_password_hash,
                    role="employee",
                )
            )

        # --- pay rates (bulk insert): one per employee, covering the
        # entire generated history plus a buffer, so no employee hits the
        # "unconfigured" gap the reports/labor-cost services otherwise
        # isolate per employee. ---------------------------------------------
        pay_rate_rows = [
            {
                "employee_id": employee.id,
                "organization_id": organization.id,
                "hourly_rate": Decimal("15.00") + Decimal(i % 20),
                "effective_from": hired_on,
                "effective_to": None,
            }
            for i, employee in enumerate(employees)
        ]
        db.session.execute(insert(EmployeePayRate), pay_rate_rows)

        # --- shifts + attendance (bulk insert) ------------------------------
        # Every employee gets one published shift per generated day (own
        # fixed start-hour/duration template, so shifts never overlap
        # across days for the same employee) and a matching attendance
        # entry -- closed for every day except a small, deterministic
        # scattering of "today" rows left open/needs_review, and a
        # scattering of employees skipped entirely on "today" to seed a
        # few genuine "absent" rows, both for dashboard-signal realism.
        published_at = datetime.combine(
            today - timedelta(days=days + 14), time(9, 0), tzinfo=timezone.utc
        )
        shift_rows = []
        attendance_rows = []
        leave_rows = []

        leave_type = LeaveType(
            organization_id=organization.id, code="VAC", name="Vacation",
            is_paid=True, requires_approval=True, blocks_scheduling=True, is_active=True,
        )
        db.session.add(leave_type)
        db.session.flush()

        for i, employee in enumerate(employees):
            start_hour, duration_hours, break_minutes = _BENCHMARK_SHIFT_TEMPLATES[
                i % len(_BENCHMARK_SHIFT_TEMPLATES)
            ]

            for day_offset in range(days):
                business_date = today - timedelta(days=day_offset)
                starts_at = datetime.combine(
                    business_date, time(start_hour, 0), tzinfo=timezone.utc
                )
                ends_at = starts_at + timedelta(hours=duration_hours)

                shift_rows.append(
                    {
                        "organization_id": organization.id,
                        "department_id": employee.department_id,
                        "employee_id": employee.id,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "business_date": business_date,
                        "break_minutes": break_minutes,
                        "status": "published",
                        "published_at": published_at,
                        "created_by_user_id": admin_user.id,
                    }
                )

                is_today = day_offset == 0
                # A small, deterministic scattering of realistic
                # exceptions, applied only to "today" so historical days
                # stay uniformly closed (a stale needs_review/open entry
                # from weeks ago would be an unrelated data-integrity
                # oddity, not a realistic seed).
                if is_today and (i % 31) == 0:
                    continue  # no attendance at all today -> "absent"
                if is_today and (i % 47) == 0:
                    attendance_rows.append(
                        {
                            "organization_id": organization.id,
                            "employee_id": employee.id,
                            "shift_id": None,
                            "started_at": starts_at,
                            "ended_at": None,
                            "business_date": business_date,
                            "break_minutes": 0,
                            "status": "needs_review",
                            "source": "web",
                            "created_by_user_id": admin_user.id,
                        }
                    )
                    continue
                if is_today and (i % 23) == 0:
                    attendance_rows.append(
                        {
                            "organization_id": organization.id,
                            "employee_id": employee.id,
                            "shift_id": None,
                            "started_at": starts_at,
                            "ended_at": None,
                            "business_date": business_date,
                            "break_minutes": 0,
                            "status": "open",
                            "source": "web",
                            "created_by_user_id": admin_user.id,
                        }
                    )
                    continue

                attendance_rows.append(
                    {
                        "organization_id": organization.id,
                        "employee_id": employee.id,
                        "shift_id": None,
                        "started_at": starts_at,
                        "ended_at": ends_at,
                        "business_date": business_date,
                        "break_minutes": break_minutes,
                        "status": "closed",
                        "source": "web",
                        "created_by_user_id": admin_user.id,
                    }
                )

            # A scattering of leave requests -- one per every 15th
            # employee, cycling through approved/pending/rejected so the
            # Leave page/report has every status represented.
            if i % 15 == 0:
                leave_start_date = today - timedelta(days=rng.randint(1, max(days, 1)))
                leave_starts_at = datetime.combine(
                    leave_start_date, time.min, tzinfo=timezone.utc
                )
                leave_ends_at = leave_starts_at + timedelta(days=1)
                cycle = (i // 15) % 3
                if cycle == 0:
                    leave_rows.append(
                        {
                            "organization_id": organization.id,
                            "employee_id": employee.id,
                            "leave_type_id": leave_type.id,
                            "starts_at": leave_starts_at,
                            "ends_at": leave_ends_at,
                            "status": "approved",
                            "reason": "Benchmark seed data",
                            "requested_by_user_id": admin_user.id,
                            "decided_by_user_id": admin_user.id,
                            "decided_at": leave_starts_at,
                        }
                    )
                elif cycle == 1:
                    leave_rows.append(
                        {
                            "organization_id": organization.id,
                            "employee_id": employee.id,
                            "leave_type_id": leave_type.id,
                            "starts_at": leave_starts_at,
                            "ends_at": leave_ends_at,
                            "status": "pending",
                            "reason": "Benchmark seed data",
                            "requested_by_user_id": admin_user.id,
                        }
                    )
                else:
                    leave_rows.append(
                        {
                            "organization_id": organization.id,
                            "employee_id": employee.id,
                            "leave_type_id": leave_type.id,
                            "starts_at": leave_starts_at,
                            "ends_at": leave_ends_at,
                            "status": "rejected",
                            "reason": "Benchmark seed data",
                            "requested_by_user_id": admin_user.id,
                            "decided_by_user_id": admin_user.id,
                            "decided_at": leave_starts_at,
                        }
                    )

        if shift_rows:
            db.session.execute(insert(Shift), shift_rows)
        if attendance_rows:
            db.session.execute(insert(AttendanceEntry), attendance_rows)
        if leave_rows:
            db.session.execute(insert(LeaveRequest), leave_rows)

        db.session.commit()
        click.echo(
            f"Seeded benchmark organization {organization_slug!r}: "
            f"{employee_count} employees across {len(departments)} "
            f"departments, {days} days of shift/attendance history "
            f"({len(shift_rows)} shifts, {len(attendance_rows)} attendance "
            f"entries, {len(leave_rows)} leave requests). Logins (fixed "
            f"password {_BENCHMARK_PASSWORD!r} -- see this command's "
            f"docstring for why it's fixed, not randomized): "
            f"{admin_user.email} (admin), {manager_users[0].email} (manager), "
            f"employee@{organization_slug}.bench.local (employee)."
        )
