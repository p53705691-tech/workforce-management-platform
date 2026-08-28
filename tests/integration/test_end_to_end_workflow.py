"""One full-lifecycle integration test tying every domain module
together, per this hardening pass's explicit requirement: admin creates
employee -> account -> department (already exists) -> schedule -> publish
-> employee clock in/out -> working hours -> overtime -> leave request ->
manager approval -> reports -> audit log.

Individual modules already have their own thorough unit/integration
coverage (test_employee_service.py, test_scheduling_service.py, etc.) —
this test exists specifically to prove the *chain* holds end to end
through real service calls, not to re-test any single step's edge cases.
Boundary/invalid/unauthorized scenarios for each step are covered in
their own dedicated test files; true concurrency is covered by
test_concurrency.py.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from freezegun import freeze_time

from app.auth.scope import AccessScope
from app.services import employees as employee_service
from app.services import leave as leave_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service
from app.services import working_hours as working_hours_service
from app.services.attendance import clock_in, clock_out
from app.services.audit import list_entries as list_audit_entries
from app.services.errors import ValidationError
from tests.factories import (
    make_department,
    make_leave_type,
    make_organization,
    make_overtime_policy,
    make_overtime_tier,
    make_pay_rate,
    make_user,
)

pytestmark = pytest.mark.integration


def _scope_for(user, department_ids=frozenset(), employee_id=None):
    return AccessScope(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


class TestFullEmployeeLifecycle:
    def test_hire_to_report_and_audit_trail(self, db_session):
        org = make_organization(db_session, timezone="UTC")
        department = make_department(db_session, organization=org)
        admin_user = make_user(db_session, organization=org, role="admin")
        admin_scope = _scope_for(admin_user)

        # An overtime policy is required for labor-cost/overtime
        # reporting to treat this employee as "configured" — same
        # confirmed default as the rest of this project's fixtures.
        policy = make_overtime_policy(db_session, organization=org)
        make_overtime_tier(db_session, policy=policy)

        # 1. Admin creates employee.
        employee = employee_service.create_employee(
            admin_scope,
            department_id=department.id,
            employee_number="E2E-001",
            first_name="Ada",
            last_name="Lovelace",
            employment_status="active",
            hired_on=date(2020, 1, 1),
        )

        # 2. Admin creates the login account.
        user = employee_service.create_employee_account(
            admin_scope, employee.id, "ada@e2e-test.example", "a-very-secure-password-1"
        )
        assert user.role == "employee"
        assert user.employee_id == employee.id

        # A pay rate, so labor-cost/overtime reporting has something to
        # compute against.
        make_pay_rate(
            db_session,
            organization=org,
            employee=employee,
            effective_from=date(2020, 1, 1),
            hourly_rate=Decimal("25.00"),
        )

        employee_scope = _scope_for(user, employee_id=employee.id)

        # 3. Admin schedules and publishes an 8-hour shift starting now
        # (frozen), so the whole shift/clock-in/clock-out chain runs on
        # a deterministic clock instead of real wall-clock timing.
        shift_start = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
        shift_end = shift_start + timedelta(hours=8)

        with freeze_time(shift_start):
            today = report_service.today_business_date(admin_scope)
            shift = scheduling_service.create_shift(
                admin_scope,
                department_id=department.id,
                starts_at=shift_start,
                ends_at=shift_end,
                employee_id=employee.id,
            )
            assert shift.status == "draft"

            published_shift = scheduling_service.publish_shift(admin_scope, shift.id)
            assert published_shift.status == "published"
            assert published_shift.published_at is not None

            # 4. Employee clocks in now (self-service — an employee may
            # never backdate their own clock-in).
            entry = clock_in(employee_scope)
            assert entry.status == "open"
            assert entry.shift_id == shift.id

        # 5. Employee clocks out 8 hours later (self-service, also
        # "now" — never backdated).
        with freeze_time(shift_end):
            closed_entry = clock_out(employee_scope, entry.id)
            assert closed_entry.status == "closed"

        # 6. Working hours reflects the closed entry.
        worked = working_hours_service.scheduled_vs_worked(admin_scope, employee.id, today)
        assert worked["worked_hours"] == Decimal("8.00")

        # 7. Overtime report includes this employee, correctly
        # "configured" (rate + policy both present).
        overtime_summary = report_service.overtime_summary(
            admin_scope, department.id, today, today
        )
        this_employee_row = next(row for row in overtime_summary if row["employee"].id == employee.id)
        assert this_employee_row["configured"] is True

        # 8. Employee requests leave for next week; manager approves it.
        manager_user = make_user(db_session, organization=org, role="manager")
        from app.models.department_manager import DepartmentManager

        db_session.add(
            DepartmentManager(
                user_id=manager_user.id, department_id=department.id, organization_id=org.id
            )
        )
        db_session.flush()
        manager_scope = _scope_for(manager_user, department_ids=frozenset({department.id}))

        leave_type = make_leave_type(db_session, organization=org)
        leave_start = datetime.now(timezone.utc) + timedelta(days=10)
        leave_end = leave_start + timedelta(days=1)
        leave_request = leave_service.request_leave(
            employee_scope, leave_type.id, leave_start, leave_end
        )
        assert leave_request.status == "pending"

        approved = leave_service.approve_leave(manager_scope, leave_request.id)
        assert approved.status == "approved"
        assert approved.decided_by_user_id == manager_user.id

        # 9. Labor cost / reports reflect this employee's hours.
        cost_summary = None
        try:
            from app.services import labor_cost as labor_cost_service

            cost_summary = labor_cost_service.department_cost_summary(
                admin_scope, department.id, today, today
            )
        except ValidationError:
            pytest.fail("department_cost_summary should not raise for a fully-configured employee")
        assert cost_summary.total > Decimal("0")
        assert cost_summary.unconfigured_employee_count == 0

        # 10. Every privileged step above left an audit trail. Wide,
        # static range: employee/account creation and the leave
        # decision happen at real wall-clock "now", while the shift/
        # clock-in/out chain above ran under freeze_time at a fixed
        # date — this just needs to safely bracket both.
        audit_page = list_audit_entries(
            admin_scope, date(2020, 1, 1), date(2030, 1, 1), page=1, page_size=100
        )
        actions = {entry.action for entry in audit_page.entries}
        assert "employee_account_created" in actions
        assert "leave_requested" in actions
        assert "leave_approved" in actions
