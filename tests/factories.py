"""Plain factory functions for building test data.

No factory library — just functions that take a db session and optional
field overrides, insert a row, and return the model instance. Callers are
responsible for giving the session a chance to flush/commit as needed by
the test (the ``db_session`` fixture handles rollback-based isolation).
"""

import itertools
from datetime import date, datetime, timezone
from decimal import Decimal

from app.auth.passwords import hash_password
from app.models.attendance_entry import AttendanceEntry
from app.models.department import Department
from app.models.department_manager import DepartmentManager
from app.models.employee import Employee
from app.models.employee_pay_rate import EmployeePayRate
from app.models.job_location import JobLocation
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.organization import Organization
from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier
from app.models.shift import Shift
from app.models.user import User

_counter = itertools.count(1)


def _next_n() -> int:
    return next(_counter)


def make_organization(session, **overrides):
    n = _next_n()
    defaults = {
        "name": f"Org {n}",
        "slug": f"org-{n}",
        "timezone": "UTC",
        "currency_code": "USD",
    }
    defaults.update(overrides)
    organization = Organization(**defaults)
    session.add(organization)
    session.flush()
    return organization


def make_department(session, organization=None, **overrides):
    n = _next_n()
    organization = organization or make_organization(session)
    defaults = {
        "organization_id": organization.id,
        "name": f"Department {n}",
        "code": f"DEPT{n}",
    }
    defaults.update(overrides)
    department = Department(**defaults)
    session.add(department)
    session.flush()
    return department


def make_job_location(session, organization=None, **overrides):
    n = _next_n()
    organization = organization or make_organization(session)
    defaults = {
        "organization_id": organization.id,
        "name": f"Job Location {n}",
        "latitude": Decimal("0"),
        "longitude": Decimal("0"),
        "radius_meters": 100,
    }
    defaults.update(overrides)
    job_location = JobLocation(**defaults)
    session.add(job_location)
    session.flush()
    return job_location


def make_employee(session, organization=None, department=None, **overrides):
    n = _next_n()
    organization = organization or make_organization(session)
    department = department or make_department(session, organization=organization)
    defaults = {
        "organization_id": organization.id,
        "department_id": department.id,
        "employee_number": f"EMP{n}",
        "first_name": "Test",
        "last_name": f"Employee{n}",
        "employment_status": "active",
        "hired_on": "2024-01-01",
    }
    defaults.update(overrides)
    employee = Employee(**defaults)
    session.add(employee)
    session.flush()
    return employee


def make_shift(
    session,
    organization=None,
    department=None,
    employee=None,
    created_by=None,
    **overrides,
):
    organization = organization or make_organization(session)
    department = department or make_department(session, organization=organization)
    created_by = created_by or make_user(session, organization=organization, role="admin")

    starts_at = overrides.pop(
        "starts_at", datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    )
    ends_at = overrides.pop("ends_at", datetime(2024, 1, 1, 17, 0, tzinfo=timezone.utc))
    # Simple default: the calendar date of starts_at as given. Tests that
    # exercise the organization-timezone attribution rule (e.g. an
    # overnight shift) should pass both starts_at and business_date
    # explicitly rather than relying on this default.
    business_date = overrides.pop("business_date", starts_at.date())

    defaults = {
        "organization_id": organization.id,
        "department_id": department.id,
        "employee_id": employee.id if employee else None,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "business_date": business_date,
        "break_minutes": 0,
        "status": "draft",
        "created_by_user_id": created_by.id,
    }
    defaults.update(overrides)
    shift = Shift(**defaults)
    session.add(shift)
    session.flush()
    return shift


def make_attendance_entry(
    session,
    organization=None,
    employee=None,
    shift=None,
    created_by=None,
    **overrides,
):
    organization = organization or make_organization(session)
    employee = employee or make_employee(session, organization=organization)

    started_at = overrides.pop(
        "started_at", datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    )
    ended_at = overrides.pop(
        "ended_at", datetime(2024, 1, 1, 17, 0, tzinfo=timezone.utc)
    )
    # Simple default: the calendar date of started_at as given, same
    # convention as make_shift. Tests exercising the organization-timezone
    # attribution rule should pass both started_at and business_date
    # explicitly rather than relying on this default.
    business_date = overrides.pop("business_date", started_at.date())
    # status defaults from whether the entry is open or closed, so an
    # override of ended_at=None alone still produces a row that satisfies
    # the DB's (status IN ('open', 'needs_review')) = (ended_at IS NULL)
    # CHECK without the caller also having to remember to set status.
    status = overrides.pop("status", "closed" if ended_at is not None else "open")

    defaults = {
        "organization_id": organization.id,
        "employee_id": employee.id,
        "shift_id": shift.id if shift else None,
        "started_at": started_at,
        "ended_at": ended_at,
        "business_date": business_date,
        "break_minutes": 0,
        "status": status,
        "source": "web",
        "created_by_user_id": created_by.id if created_by else None,
    }
    defaults.update(overrides)
    entry = AttendanceEntry(**defaults)
    session.add(entry)
    session.flush()
    return entry


def make_overtime_policy(session, organization=None, **overrides):
    n = _next_n()
    organization = organization or make_organization(session)
    defaults = {
        "organization_id": organization.id,
        "name": f"Overtime Policy {n}",
        "daily_threshold_hours": Decimal("8.00"),
        "weekly_threshold_hours": Decimal("40.00"),
        "week_start_day": 0,
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
    }
    defaults.update(overrides)
    policy = OvertimePolicy(**defaults)
    session.add(policy)
    session.flush()
    return policy


def make_overtime_tier(session, policy=None, **overrides):
    policy = policy or make_overtime_policy(session)
    defaults = {
        "policy_id": policy.id,
        "scope": "daily",
        "tier_order": 0,
        "from_hours": Decimal("0.00"),
        "to_hours": None,
        "multiplier": Decimal("1.50"),
    }
    defaults.update(overrides)
    tier = OvertimeTier(**defaults)
    session.add(tier)
    session.flush()
    return tier


def make_pay_rate(session, organization=None, employee=None, **overrides):
    organization = organization or make_organization(session)
    employee = employee or make_employee(session, organization=organization)
    defaults = {
        "employee_id": employee.id,
        "organization_id": organization.id,
        "hourly_rate": Decimal("20.0000"),
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
    }
    defaults.update(overrides)
    pay_rate = EmployeePayRate(**defaults)
    session.add(pay_rate)
    session.flush()
    return pay_rate


def make_leave_type(session, organization=None, **overrides):
    n = _next_n()
    organization = organization or make_organization(session)
    defaults = {
        "organization_id": organization.id,
        "code": f"LEAVE{n}",
        "name": f"Leave Type {n}",
        "is_paid": True,
        "requires_approval": True,
        "blocks_scheduling": True,
        "is_active": True,
    }
    defaults.update(overrides)
    leave_type = LeaveType(**defaults)
    session.add(leave_type)
    session.flush()
    return leave_type


def make_leave_request(
    session,
    organization=None,
    employee=None,
    leave_type=None,
    requested_by=None,
    **overrides,
):
    organization = organization or make_organization(session)
    employee = employee or make_employee(session, organization=organization)
    leave_type = leave_type or make_leave_type(session, organization=organization)
    requested_by = requested_by or make_user(
        session, organization=organization, role="admin"
    )

    defaults = {
        "organization_id": organization.id,
        "employee_id": employee.id,
        "leave_type_id": leave_type.id,
        "starts_at": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        "ends_at": datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        "status": "pending",
        "requested_by_user_id": requested_by.id,
    }
    defaults.update(overrides)
    leave_request = LeaveRequest(**defaults)
    session.add(leave_request)
    session.flush()
    return leave_request


def make_department_manager(session, user=None, department=None, organization=None):
    organization = organization or make_organization(session)
    department = department or make_department(session, organization=organization)
    user = user or make_user(session, organization=organization, role="manager")
    manager_link = DepartmentManager(
        user_id=user.id,
        department_id=department.id,
        organization_id=organization.id,
    )
    session.add(manager_link)
    session.flush()
    return manager_link


def make_user(session, organization=None, password="correct horse battery staple", **overrides):
    n = _next_n()
    organization = organization or make_organization(session)
    defaults = {
        "organization_id": organization.id,
        "email": f"user{n}@example.com",
        "password_hash": hash_password(password),
        "role": "admin",
    }
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    session.flush()
    return user
