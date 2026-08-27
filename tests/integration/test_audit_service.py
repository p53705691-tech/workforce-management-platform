"""Integration tests for app.services.audit and its wiring into login and
the other privileged/sensitive actions called out by this milestone.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from werkzeug.exceptions import Forbidden

from app.auth.scope import AccessScope
from app.auth.service import authenticate
from app.models.audit_log import AuditLog
from app.models.employee_pay_rate import EmployeePayRate
from app.models.user import User
from app.services import attendance as attendance_service
from app.services import audit as audit_service
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services import leave as leave_service
from app.services import pay_rates as pay_rate_service
from app.services import scheduling as scheduling_service
from tests.factories import (
    make_attendance_entry,
    make_department,
    make_employee,
    make_leave_request,
    make_leave_type,
    make_organization,
    make_shift,
    make_user,
)

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery staple"


def _scope(role, organization_id, user_id, department_ids=frozenset(), employee_id=None):
    return AccessScope(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


def _last_entry(db_session, action):
    return (
        db_session.query(AuditLog)
        .filter_by(action=action)
        .order_by(AuditLog.id.desc())
        .first()
    )


class TestLoginAuditing:
    def test_wrong_password_records_a_failed_login_with_no_actor(self, db_session):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        authenticate(user.email, "not the password")

        entry = _last_entry(db_session, "login_failed")
        assert entry is not None
        assert entry.actor_user_id is None
        assert entry.organization_id == org.id
        assert entry.entity_id == user.id

    def test_nonexistent_email_records_a_failed_login_with_no_organization_context(
        self, db_session
    ):
        authenticate("nobody@example.com", "whatever")

        entry = _last_entry(db_session, "login_failed")
        assert entry is not None
        assert entry.actor_user_id is None
        assert entry.organization_id is None

    def test_successful_login_records_the_correct_actor(self, db_session):
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)

        authenticate(user.email, PASSWORD)

        entry = _last_entry(db_session, "login_success")
        assert entry is not None
        assert entry.actor_user_id == user.id
        assert entry.organization_id == org.id


class TestPayRateAuditing:
    def test_pay_rate_change_never_records_the_rate_value(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        pay_rate_service.set_pay_rate(
            scope, employee.id, Decimal("123.4567"), date(2026, 1, 1)
        )

        entry = _last_entry(db_session, "pay_rate_set")
        assert entry is not None
        assert entry.entity_id == employee.id
        assert entry.actor_user_id == admin.id
        assert entry.changes == {
            "effective_from": "2026-01-01",
            "effective_to": None,
        }
        # Belt-and-suspenders: the rate value must not appear anywhere in
        # the stored JSON, under any key.
        assert "123.4567" not in str(entry.changes)
        assert "hourly_rate" not in entry.changes


class TestAuditIsInTheSameTransactionAsItsPrimaryWrite:
    """Round A fix: audit.record() no longer commits on its own -- every
    call site's existing single primary-write commit must cover the
    audit entry too. Proven here by forcing the audit write to fail
    *after* the primary object is staged and confirming the primary
    write rolls back with it, rather than partially persisting with no
    audit trail (the exact gap this fix closes).
    """

    def test_audit_failure_rolls_back_the_pay_rate_it_would_have_described(
        self, db_session, monkeypatch
    ):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        def _boom(*args, **kwargs):
            raise RuntimeError("audit write failed")

        monkeypatch.setattr(audit_service, "record", _boom)

        with pytest.raises(RuntimeError):
            pay_rate_service.set_pay_rate(
                scope, employee.id, Decimal("50.0000"), date(2026, 1, 1)
            )

        # Before this fix, set_pay_rate would already have committed the
        # pay rate before ever calling audit.record(), so this rollback
        # would find nothing to undo and the assertion below would fail.
        db_session.rollback()
        assert (
            db_session.query(EmployeePayRate)
            .filter_by(employee_id=employee.id)
            .count()
            == 0
        )

    def test_audit_failure_rolls_back_the_failed_login_count_it_would_have_described(
        self, db_session, monkeypatch
    ):
        """Round B fix: app.auth.service.authenticate() had the identical
        commit-then-audit gap Round A fixed everywhere else. The failed-
        login increment and its audit row must share one transaction, the
        same as every other privileged write — otherwise a crash between
        the two commits could silently increment (and even lock) an
        account with no audit trail explaining why. Rolling the increment
        back together with the failed audit write is the right behavior
        here (not just "acceptable"): the counter and its audit trail
        must never be allowed to diverge from each other.
        """
        org = make_organization(db_session)
        user = make_user(db_session, organization=org, password=PASSWORD)
        user_id = user.id
        # Establishes a savepoint boundary via the fixture's
        # create-savepoint join mode (see conftest.db_session's
        # docstring), so the rollback below only undoes the failed
        # authenticate() call, not this setup — see
        # test_attendance_constraints.py's identical note on why a bare
        # db_session.rollback() otherwise undoes the whole test.
        db_session.commit()

        def _boom(*args, **kwargs):
            raise RuntimeError("audit write failed")

        monkeypatch.setattr(audit_service, "record", _boom)

        with pytest.raises(RuntimeError):
            authenticate(user.email, "wrong password")

        db_session.rollback()
        reloaded = db_session.get(User, user_id)
        assert reloaded.failed_login_count == 0
        assert reloaded.locked_until is None


class TestOtherPrivilegedActionAuditing:
    def test_employee_termination_records_an_audit_row(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        employee_service.terminate_employee(scope, employee.id, date(2026, 6, 1))

        entry = _last_entry(db_session, "employee_terminated")
        assert entry is not None
        assert entry.entity_id == employee.id
        assert entry.actor_user_id == admin.id

    def test_shift_publish_and_cancel_record_audit_rows(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        shift = make_shift(
            db_session, organization=org, department=department, employee=employee,
            created_by=admin,
        )
        scope = _scope("admin", org.id, admin.id)

        scheduling_service.publish_shift(scope, shift.id)
        published_entry = _last_entry(db_session, "shift_published")
        assert published_entry is not None
        assert published_entry.entity_id == shift.id

        scheduling_service.cancel_shift(scope, shift.id)
        cancelled_entry = _last_entry(db_session, "shift_cancelled")
        assert cancelled_entry is not None
        assert cancelled_entry.entity_id == shift.id

    def test_create_employee_records_an_audit_row(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        employee = employee_service.create_employee(
            scope,
            department_id=department.id,
            employee_number="E-AUDIT-1",
            first_name="Audit",
            last_name="Test",
            employment_status="active",
            hired_on=date(2024, 1, 1),
        )

        entry = _last_entry(db_session, "employee_created")
        assert entry is not None
        assert entry.entity_id == employee.id
        assert entry.actor_user_id == admin.id

    def test_create_and_update_department_record_audit_rows(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        department = department_service.create_department(scope, name="Ops", code="OPS-AUDIT")

        created_entry = _last_entry(db_session, "department_created")
        assert created_entry is not None
        assert created_entry.entity_id == department.id

        department_service.update_department(scope, department.id, name="Renamed")

        updated_entry = _last_entry(db_session, "department_updated")
        assert updated_entry is not None
        assert updated_entry.entity_id == department.id

    def test_create_update_and_assign_shift_record_audit_rows(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        shift = scheduling_service.create_shift(
            scope,
            department_id=department.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
        )
        created_entry = _last_entry(db_session, "shift_created")
        assert created_entry is not None
        assert created_entry.entity_id == shift.id

        scheduling_service.update_shift(scope, shift.id, notes="Adjusted.")
        updated_entry = _last_entry(db_session, "shift_updated")
        assert updated_entry is not None
        assert updated_entry.entity_id == shift.id

        scheduling_service.assign_employee(scope, shift.id, employee.id)
        assigned_entry = _last_entry(db_session, "shift_assigned")
        assert assigned_entry is not None
        assert assigned_entry.entity_id == shift.id
        assert assigned_entry.changes["employee_id"] == employee.id

    def test_request_leave_records_an_audit_row(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        leave_type = make_leave_type(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        leave_request = leave_service.request_leave(
            scope,
            leave_type_id=leave_type.id,
            starts_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            employee_id=employee.id,
        )

        entry = _last_entry(db_session, "leave_requested")
        assert entry is not None
        assert entry.entity_id == leave_request.id
        assert entry.actor_user_id == admin.id

    def test_leave_approve_and_reject_record_audit_rows_without_the_decision_note(
        self, db_session
    ):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        leave_type = make_leave_type(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        approved_request = make_leave_request(
            db_session, organization=org, employee=employee, leave_type=leave_type,
            requested_by=admin,
        )
        leave_service.approve_leave(
            scope, approved_request.id, decision_note="Personal medical appointment."
        )
        approved_entry = _last_entry(db_session, "leave_approved")
        assert approved_entry is not None
        assert approved_entry.entity_id == approved_request.id
        assert "medical" not in str(approved_entry.changes)

        # A distinct, non-overlapping window (the DB's exclusion constraint
        # forbids overlapping pending/approved leave for the same employee).
        rejected_request = make_leave_request(
            db_session, organization=org, employee=employee, leave_type=leave_type,
            requested_by=admin,
            starts_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 2, 1, 17, 0, tzinfo=timezone.utc),
        )
        leave_service.reject_leave(
            scope, rejected_request.id, decision_note="Staffing shortage that week."
        )
        rejected_entry = _last_entry(db_session, "leave_rejected")
        assert rejected_entry is not None
        assert rejected_entry.entity_id == rejected_request.id
        assert "Staffing" not in str(rejected_entry.changes)

    def test_attendance_correction_records_an_audit_row(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin
        )
        scope = _scope("admin", org.id, admin.id)

        attendance_service.correct_entry(
            scope, entry.id, edit_reason="Adjusted per timesheet review."
        )

        audit_entry = _last_entry(db_session, "attendance_corrected")
        assert audit_entry is not None
        assert audit_entry.entity_id == entry.id
        assert audit_entry.changes["employee_id"] == employee.id

    def test_attendance_correction_never_records_the_edit_reason(self, db_session):
        """Round C fix: edit_reason is free-text that may contain a
        personal/medical circumstance -- the same privacy reasoning
        already applied to leave's decision_note (see
        test_leave_approve_and_reject_record_audit_rows_without_the_decision_note
        above) applies equally here. Mirrors
        TestPayRateAuditing.test_pay_rate_change_never_records_the_rate_value's
        belt-and-suspenders shape.
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        admin = make_user(db_session, organization=org, role="admin")
        entry = make_attendance_entry(
            db_session, organization=org, employee=employee, created_by=admin
        )
        scope = _scope("admin", org.id, admin.id)

        attendance_service.correct_entry(
            scope, entry.id, edit_reason="Employee has a confidential medical condition."
        )

        audit_entry = _last_entry(db_session, "attendance_corrected")
        assert audit_entry is not None
        assert "edit_reason" not in audit_entry.changes
        assert "medical" not in str(audit_entry.changes)

    def test_cancel_leave_on_a_pending_request_records_an_audit_row(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        leave_type = make_leave_type(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        pending_request = make_leave_request(
            db_session, organization=org, employee=employee, leave_type=leave_type,
            requested_by=admin,
        )

        leave_service.cancel_leave(scope, pending_request.id)

        entry = _last_entry(db_session, "leave_cancelled")
        assert entry is not None
        assert entry.entity_id == pending_request.id
        assert entry.changes["previous_status"] == "pending"

    def test_cancel_leave_on_an_approved_request_records_a_distinguishable_audit_row(
        self, db_session
    ):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        leave_type = make_leave_type(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        approved_request = make_leave_request(
            db_session, organization=org, employee=employee, leave_type=leave_type,
            requested_by=admin,
        )
        leave_service.approve_leave(scope, approved_request.id)
        approved_entry = _last_entry(db_session, "leave_approved")
        assert approved_entry is not None

        leave_service.cancel_leave(scope, approved_request.id)
        cancelled_entry = _last_entry(db_session, "leave_cancelled")

        assert cancelled_entry is not None
        assert cancelled_entry.entity_id == approved_request.id
        assert cancelled_entry.changes["previous_status"] == "approved"
        # Distinguishable from the original approval: a different action
        # name and a different row entirely, not an update to the
        # existing "leave_approved" entry (this table is append-only).
        assert cancelled_entry.id != approved_entry.id
        assert cancelled_entry.action != approved_entry.action

    def test_update_employee_records_an_audit_row_for_department_and_status_changes(
        self, db_session
    ):
        org = make_organization(db_session)
        old_department = make_department(db_session, organization=org)
        new_department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=old_department)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        employee_service.update_employee(
            scope,
            employee.id,
            department_id=new_department.id,
            employee_number=employee.employee_number,
            first_name=employee.first_name,
            last_name=employee.last_name,
            employment_status="inactive",
        )

        entry = _last_entry(db_session, "employee_updated")
        assert entry is not None
        assert entry.entity_id == employee.id
        assert entry.actor_user_id == admin.id
        assert "department_id" in entry.changes["fields_changed"]
        assert "employment_status" in entry.changes["fields_changed"]

    def test_deactivate_department_records_an_audit_row(self, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        department_service.deactivate_department(scope, department.id)

        entry = _last_entry(db_session, "department_deactivated")
        assert entry is not None
        assert entry.entity_id == department.id
        assert entry.actor_user_id == admin.id


class TestListEntries:
    """Round C fix: app.routes.audit used to build and execute its own
    db.session.query(AuditLog) inline -- the one route in this codebase
    that queried the database directly instead of going through a
    service. That query's exact behavior (org scoping, date-range
    filtering, admin-only, pagination) is now covered here at the
    service layer, relocated unchanged.
    """

    def test_non_admin_is_forbidden(self, db_session):
        org = make_organization(db_session)
        manager = make_user(db_session, organization=org, role="manager")
        scope = _scope("manager", org.id, manager.id)

        with pytest.raises(Forbidden):
            audit_service.list_entries(scope, date(2026, 1, 1), date(2026, 1, 31), page=1)

    def test_only_the_callers_own_organization_is_returned(self, db_session):
        org = make_organization(db_session)
        other_org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        other_admin = make_user(db_session, organization=other_org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        authenticate(admin.email, "wrong password")
        authenticate(other_admin.email, "wrong password")

        today = date.today()
        page = audit_service.list_entries(
            scope, today - timedelta(days=1), today + timedelta(days=1), page=1
        )

        assert page.entries
        assert all(entry.organization_id == org.id for entry in page.entries)

    def test_entries_outside_the_date_range_are_excluded(self, db_session):
        org = make_organization(db_session)
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        employee_service.terminate_employee(scope, employee.id, date(2026, 6, 1))

        # A window that does not cover "now" (when the row above was
        # actually created) must exclude it.
        far_past = date(2020, 1, 1)
        page = audit_service.list_entries(scope, far_past, far_past, page=1)

        assert all(entry.entity_id != employee.id for entry in page.entries)

    def test_org_local_evening_event_is_included_in_the_default_today_window(
        self, db_session
    ):
        """Bug: list_entries used to build its date-range bounds in UTC
        even though the route's default range (and every displayed
        timestamp) is the organization's own local date (rule A1). For
        any organization behind UTC, an event late in the local evening
        already falls on the *next* UTC calendar day and was silently
        excluded from "today"'s default window.

        ``created_at`` is a server-side ``func.now()`` default (real
        wall-clock time, not something ``freeze_time`` can control), so
        the boundary condition is reproduced by setting it directly on
        the row after creation rather than by freezing the clock.
        """
        org = make_organization(db_session, timezone="Pacific/Honolulu")
        employee = make_employee(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        employee_service.terminate_employee(scope, employee.id, date(2026, 6, 9))
        entry = _last_entry(db_session, "employee_terminated")
        # 2026-06-09 20:00 in Honolulu (UTC-10) is 2026-06-10 06:00 UTC --
        # already the next UTC calendar day.
        entry.created_at = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
        db_session.flush()

        page = audit_service.list_entries(scope, date(2026, 6, 9), date(2026, 6, 9), page=1)

        assert any(e.id == entry.id for e in page.entries)

    def test_pagination_reports_has_next_correctly(self, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin")
        scope = _scope("admin", org.id, admin.id)

        for offset in range(3):
            department = make_department(db_session, organization=org)
            department_service.deactivate_department(scope, department.id)

        today = date.today()
        start = today - timedelta(days=1)
        end = today + timedelta(days=1)

        first_page = audit_service.list_entries(scope, start, end, page=1, page_size=2)
        assert len(first_page.entries) == 2
        assert first_page.has_next is True

        second_page = audit_service.list_entries(scope, start, end, page=2, page_size=2)
        assert len(second_page.entries) == 1
        assert second_page.has_next is False
