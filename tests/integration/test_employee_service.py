"""Integration tests for app.services.employees — DB + authorization."""

import smtplib

import pytest
from werkzeug.exceptions import Forbidden, NotFound

from app.auth.scope import AccessScope
from app.services import departments as department_service
from app.services import employees as employee_service
from app.services.errors import ValidationError
from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.integration


def _scope(role, organization_id, department_ids=frozenset(), employee_id=None, user_id=1):
    return AccessScope(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_ids=department_ids,
        employee_id=employee_id,
    )


def _required_fields(department_id, **overrides):
    fields = {
        "department_id": department_id,
        "employee_number": "E1",
        "first_name": "A",
        "last_name": "B",
        "employment_status": "active",
        "hired_on": "2024-01-01",
    }
    fields.update(overrides)
    return fields


def test_admin_lists_every_employee_in_their_organization(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    emp_a = make_employee(db_session, organization=org, department=department)
    emp_b = make_employee(db_session, organization=org, department=department)
    other_org = make_organization(db_session)
    make_employee(db_session, organization=other_org)

    result = employee_service.list_employees(_scope("admin", org.id))

    assert {e.id for e in result} == {emp_a.id, emp_b.id}


def test_manager_lists_only_employees_in_managed_departments(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    managed_emp = make_employee(db_session, organization=org, department=managed_dept)
    make_employee(db_session, organization=org, department=other_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))
    result = employee_service.list_employees(scope)

    assert [e.id for e in result] == [managed_emp.id]


def test_employee_lists_only_their_own_record(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own = make_employee(db_session, organization=org, department=department)
    make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=own.id)
    result = employee_service.list_employees(scope)

    assert [e.id for e in result] == [own.id]


def test_get_employee_outside_manager_scope_is_not_found(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))

    with pytest.raises(NotFound):
        employee_service.get_employee(scope, other_employee.id)


def test_get_employee_from_another_organization_is_not_found(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    employee_in_b = make_employee(db_session, organization=org_b)

    with pytest.raises(NotFound):
        employee_service.get_employee(_scope("admin", org_a.id), employee_in_b.id)


def test_employee_cannot_get_another_employees_record(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    own = make_employee(db_session, organization=org, department=department)
    other = make_employee(db_session, organization=org, department=department)

    scope = _scope("employee", org.id, employee_id=own.id)

    with pytest.raises(NotFound):
        employee_service.get_employee(scope, other.id)


def test_create_employee_requires_admin_role(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    scope = _scope("manager", org.id, department_ids=frozenset({department.id}))

    with pytest.raises(Forbidden):
        employee_service.create_employee(scope, **_required_fields(department.id))


def test_create_employee_rejects_a_department_from_another_organization(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    foreign_department = make_department(db_session, organization=other_org)

    with pytest.raises(ValidationError):
        employee_service.create_employee(
            _scope("admin", org.id), **_required_fields(foreign_department.id)
        )


def test_create_employee_rejects_a_missing_required_field(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    fields = _required_fields(department.id)
    del fields["hired_on"]

    with pytest.raises(ValidationError):
        employee_service.create_employee(_scope("admin", org.id), **fields)


def test_create_employee_rejects_an_unknown_field(db_session):
    org = make_organization(db_session)
    other_org = make_organization(db_session)
    department = make_department(db_session, organization=org)

    with pytest.raises(ValidationError):
        # organization_id is not part of the create allowlist at all — a
        # caller cannot smuggle a foreign organization in through it.
        employee_service.create_employee(
            _scope("admin", org.id),
            **_required_fields(department.id, organization_id=other_org.id),
        )


def test_admin_creates_employee_scoped_to_their_own_organization(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    # A real user is required here (not the synthetic user_id=1 default):
    # create_employee now writes an audit_logs row whose actor_user_id
    # has a real FK to users.id.
    admin = make_user(db_session, organization=org, role="admin")

    employee = employee_service.create_employee(
        _scope("admin", org.id, user_id=admin.id), **_required_fields(department.id)
    )

    assert employee.organization_id == org.id


def test_manager_cannot_update_employee_outside_managed_departments(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    other_employee = make_employee(db_session, organization=org, department=other_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))

    with pytest.raises(NotFound):
        employee_service.update_employee(scope, other_employee.id, first_name="Changed")


def test_manager_updates_employee_in_a_managed_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)
    # A real user is required here (not the synthetic user_id=1 default):
    # update_employee now writes an audit_logs row whose actor_user_id has
    # a real FK to users.id (see test_terminate_employee_sets_status_and_date_together's
    # identical note).
    manager = make_user(db_session, organization=org, role="manager")

    scope = _scope(
        "manager", org.id, department_ids=frozenset({managed_dept.id}), user_id=manager.id
    )
    updated = employee_service.update_employee(scope, employee.id, first_name="Changed")

    assert updated.first_name == "Changed"


def test_update_employee_rejects_an_unknown_field(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)

    with pytest.raises(ValidationError):
        employee_service.update_employee(
            _scope("admin", org.id), employee.id, organization_id=999
        )


def test_update_employee_rejects_setting_status_to_terminated_directly(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)

    with pytest.raises(ValidationError):
        employee_service.update_employee(
            _scope("admin", org.id), employee.id, employment_status="terminated"
        )


def test_manager_cannot_reassign_employee_to_an_unmanaged_department(db_session):
    org = make_organization(db_session)
    managed_dept = make_department(db_session, organization=org)
    other_dept = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=managed_dept)

    scope = _scope("manager", org.id, department_ids=frozenset({managed_dept.id}))

    with pytest.raises(ValidationError):
        employee_service.update_employee(scope, employee.id, department_id=other_dept.id)


def test_create_employee_rejects_a_deactivated_department(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    scope = _scope("admin", org.id, user_id=admin.id)
    department_service.deactivate_department(scope, department.id)

    with pytest.raises(ValidationError):
        employee_service.create_employee(scope, **_required_fields(department.id))


def test_update_employee_rejects_reassigning_into_a_deactivated_department(db_session):
    org = make_organization(db_session)
    active_department = make_department(db_session, organization=org)
    inactive_department = make_department(db_session, organization=org)
    admin = make_user(db_session, organization=org, role="admin")
    scope = _scope("admin", org.id, user_id=admin.id)
    department_service.deactivate_department(scope, inactive_department.id)
    employee = make_employee(db_session, organization=org, department=active_department)

    with pytest.raises(ValidationError):
        employee_service.update_employee(
            scope, employee.id, department_id=inactive_department.id
        )


def test_update_employee_allows_unrelated_edits_while_in_a_deactivated_department(
    db_session,
):
    """Deactivation must not retroactively block editing an employee
    already there — only new placement into (or reassignment into) an
    inactive department is rejected.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    scope = _scope("admin", org.id, user_id=admin.id)
    department_service.deactivate_department(scope, department.id)

    updated = employee_service.update_employee(
        scope,
        employee.id,
        first_name="Changed",
        department_id=department.id,
    )

    assert updated.first_name == "Changed"
    assert updated.department_id == department.id


def test_terminate_employee_sets_status_and_date_together(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    # A real user is required here (not the synthetic user_id=1 default):
    # terminate_employee now writes an audit_logs row whose actor_user_id
    # has a real FK to users.id.
    admin = make_user(db_session, organization=org, role="admin")

    terminated = employee_service.terminate_employee(
        _scope("admin", org.id, user_id=admin.id), employee.id, "2024-06-01"
    )

    assert terminated.employment_status == "terminated"
    assert str(terminated.terminated_on) == "2024-06-01"


def test_terminate_employee_rejects_a_termination_date_before_hire_date(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(
        db_session, organization=org, department=department, hired_on="2024-01-01"
    )
    admin = make_user(db_session, organization=org, role="admin")

    with pytest.raises(ValidationError):
        employee_service.terminate_employee(
            _scope("admin", org.id, user_id=admin.id), employee.id, "2023-12-31"
        )


def test_terminate_employee_requires_admin_role(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    scope = _scope("manager", org.id, department_ids=frozenset({department.id}))

    with pytest.raises(Forbidden):
        employee_service.terminate_employee(scope, employee.id, "2024-06-01")


def test_terminate_employee_deactivates_the_linked_login(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")
    login = make_user(
        db_session, organization=org, role="employee", employee_id=employee.id
    )
    assert login.is_active is True

    employee_service.terminate_employee(
        _scope("admin", org.id, user_id=admin.id), employee.id, "2024-06-01"
    )

    db_session.refresh(login)
    assert login.is_active is False


def test_terminate_employee_with_no_linked_login_still_succeeds(db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    admin = make_user(db_session, organization=org, role="admin")

    terminated = employee_service.terminate_employee(
        _scope("admin", org.id, user_id=admin.id), employee.id, "2024-06-01"
    )

    assert terminated.employment_status == "terminated"


# --- Notification wiring (app.services.notifications) -----------------
#
# create_employee_account/reset_employee_account_password each notify
# the employee: a missing Employee.email is skipped silently, and a
# simulated SMTP failure must never prevent the primary write from
# committing (see app.services.notifications's module docstring).


def test_create_employee_account_notifies_the_employee(db_session, monkeypatch):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(
        db_session, organization=org, department=department, email="jane@example.com"
    )
    admin = make_user(db_session, organization=org, role="admin")

    sent = []
    monkeypatch.setattr(
        employee_service.notification_service,
        "send_email",
        lambda to, subject, template_name, **ctx: sent.append((to, subject, template_name, ctx)),
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    employee_service.create_employee_account(
        scope, employee.id, "jane.login@example.com", "correct horse battery staple"
    )

    assert len(sent) == 1
    to, subject, template_name, context = sent[0]
    assert to == "jane@example.com"
    assert template_name == "account_created"
    assert context["login_email"] == "jane.login@example.com"
    # The password itself must never appear anywhere in the notification.
    assert "correct horse battery staple" not in str(context)


def test_create_employee_account_skips_notification_silently_without_an_email(
    db_session, monkeypatch
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    assert employee.email is None
    admin = make_user(db_session, organization=org, role="admin")

    sent = []
    monkeypatch.setattr(
        employee_service.notification_service,
        "send_email",
        lambda *args, **kwargs: sent.append(args),
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    user = employee_service.create_employee_account(
        scope, employee.id, "jane.login@example.com", "correct horse battery staple"
    )

    assert user.email == "jane.login@example.com"
    assert sent == []


def test_reset_employee_account_password_notifies_the_employee(db_session, monkeypatch):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(
        db_session, organization=org, department=department, email="jane@example.com"
    )
    admin = make_user(db_session, organization=org, role="admin")
    make_user(
        db_session,
        organization=org,
        role="employee",
        employee_id=employee.id,
        email="jane.login@example.com",
    )

    sent = []
    monkeypatch.setattr(
        employee_service.notification_service,
        "send_email",
        lambda to, subject, template_name, **ctx: sent.append((to, subject, template_name, ctx)),
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    employee_service.reset_employee_account_password(
        scope, employee.id, "another correct horse battery staple"
    )

    assert len(sent) == 1
    to, subject, template_name, context = sent[0]
    assert to == "jane@example.com"
    assert template_name == "account_password_reset"
    assert context["login_email"] == "jane.login@example.com"
    assert "another correct horse battery staple" not in str(context)


def test_reset_employee_account_password_skips_notification_silently_without_an_email(
    db_session, monkeypatch
):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(db_session, organization=org, department=department)
    assert employee.email is None
    admin = make_user(db_session, organization=org, role="admin")
    make_user(db_session, organization=org, role="employee", employee_id=employee.id)

    sent = []
    monkeypatch.setattr(
        employee_service.notification_service,
        "send_email",
        lambda *args, **kwargs: sent.append(args),
    )

    scope = _scope("admin", org.id, user_id=admin.id)
    reset_user = employee_service.reset_employee_account_password(
        scope, employee.id, "another correct horse battery staple"
    )

    assert reset_user is not None
    assert sent == []


def test_reset_employee_account_password_succeeds_even_when_the_smtp_server_is_unreachable(
    db_session, app, monkeypatch
):
    """The primary write (resetting the password) must commit and be
    returned to the caller even if the notification email's SMTP send
    fails outright — see app.services.notifications's module docstring.
    """
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee = make_employee(
        db_session, organization=org, department=department, email="jane@example.com"
    )
    admin = make_user(db_session, organization=org, role="admin")
    make_user(db_session, organization=org, role="employee", employee_id=employee.id)

    monkeypatch.setitem(app.config, "MAIL_BACKEND", "smtp")
    monkeypatch.setitem(app.config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setitem(app.config, "MAIL_FROM_ADDRESS", "noreply@acme.test")

    def _boom(*args, **kwargs):
        raise TimeoutError("smtp server unreachable")

    monkeypatch.setattr(smtplib, "SMTP", _boom)

    scope = _scope("admin", org.id, user_id=admin.id)
    reset_user = employee_service.reset_employee_account_password(
        scope, employee.id, "another correct horse battery staple"
    )

    assert reset_user.password_hash is not None
