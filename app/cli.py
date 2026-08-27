"""Flask CLI commands for maintenance operations.

Registered on the app in ``create_app`` (see ``app/__init__.py``), same
place every blueprint gets registered. These are operator-invoked
maintenance tasks, not user-facing routes, so they live outside
``app/routes``.
"""

import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import secrets

import click
from flask import Flask

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
