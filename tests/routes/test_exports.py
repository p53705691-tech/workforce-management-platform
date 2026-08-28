"""Export routes (CSV/PDF): authorization and cross-organization scope.

Every export endpoint reuses the same ``role_required``/``AccessScope``
path its HTML counterpart already uses (see app.routes.* and
app.services.exports/pdf_reports' module docstrings) — these tests exist
to prove that in practice, matching the existing IDOR-sweep pattern in
test_idor_sweep.py: a cross-organization id gets a plain 404, an
unauthorized role gets 403, and never a 500.
"""

from datetime import date, timedelta

import pytest

from app.models.department_manager import DepartmentManager
from tests.factories import (
    make_department,
    make_employee,
    make_organization,
    make_overtime_policy,
    make_pay_rate,
    make_user,
)

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def _make_manager(db_session, org, *managed_departments):
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    for department in managed_departments:
        db_session.add(
            DepartmentManager(
                user_id=manager.id, department_id=department.id, organization_id=org.id
            )
        )
    db_session.flush()
    return manager


def _range():
    end = date.today()
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


class TestExportContentTypes:
    """One admin, happy-path smoke test per export area — the full data
    correctness of each is covered at the service layer
    (tests/integration/test_reports_service.py etc.); this just proves
    each route actually returns the right file type.
    """

    def test_attendance_csv_and_pdf(self, client, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        _login(client, admin)
        start, end = _range()

        csv_response = client.get(f"/attendance?start={start}&end={end}&format=csv")
        pdf_response = client.get(f"/attendance?start={start}&end={end}&format=pdf")

        assert csv_response.status_code == 200
        assert csv_response.content_type.startswith("text/csv")
        assert pdf_response.status_code == 200
        assert pdf_response.content_type == "application/pdf"

    def test_overtime_csv_and_pdf(self, client, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        _login(client, admin)
        start, end = _range()

        csv_response = client.get(
            f"/reports/overtime?department_id={department.id}&start={start}&end={end}&format=csv"
        )
        pdf_response = client.get(
            f"/reports/overtime?department_id={department.id}&start={start}&end={end}&format=pdf"
        )

        assert csv_response.status_code == 200
        assert csv_response.content_type.startswith("text/csv")
        assert pdf_response.status_code == 200
        assert pdf_response.content_type == "application/pdf"

    def test_working_hours_csv_and_pdf(self, client, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        _login(client, admin)
        start, end = _range()

        csv_response = client.get(
            f"/reports/working-hours?department_id={department.id}&start={start}&end={end}&format=csv"
        )
        pdf_response = client.get(
            f"/reports/working-hours?department_id={department.id}&start={start}&end={end}&format=pdf"
        )

        assert csv_response.status_code == 200
        assert csv_response.content_type.startswith("text/csv")
        assert pdf_response.status_code == 200
        assert pdf_response.content_type == "application/pdf"

    def test_leave_csv_and_pdf(self, client, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        _login(client, admin)

        csv_response = client.get("/leave?format=csv")
        pdf_response = client.get("/leave?format=pdf")

        assert csv_response.status_code == 200
        assert csv_response.content_type.startswith("text/csv")
        assert pdf_response.status_code == 200
        assert pdf_response.content_type == "application/pdf"

    def test_labor_cost_department_csv_and_pdf(self, client, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        _login(client, admin)
        start, end = _range()

        csv_response = client.get(
            f"/labor-cost?department_id={department.id}&start={start}&end={end}&format=csv"
        )
        pdf_response = client.get(
            f"/labor-cost?department_id={department.id}&start={start}&end={end}&format=pdf"
        )

        assert csv_response.status_code == 200
        assert csv_response.content_type.startswith("text/csv")
        assert pdf_response.status_code == 200
        assert pdf_response.content_type == "application/pdf"

    def test_labor_cost_employee_payroll_csv_and_pdf_admin_only(self, client, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        make_pay_rate(db_session, organization=org, employee=employee, effective_from=date(2020, 1, 1))
        make_overtime_policy(db_session, organization=org)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        _login(client, admin)
        start, end = _range()

        csv_response = client.get(
            f"/labor-cost/employees/{employee.id}?start={start}&end={end}&format=csv"
        )
        pdf_response = client.get(
            f"/labor-cost/employees/{employee.id}?start={start}&end={end}&format=pdf"
        )

        assert csv_response.status_code == 200
        assert csv_response.content_type.startswith("text/csv")
        assert pdf_response.status_code == 200
        assert pdf_response.content_type == "application/pdf"


class TestExportAuthorization:
    def test_manager_cannot_export_per_employee_payroll(self, client, db_session):
        """Rule A4: the one export that carries a rate/cost per employee
        must stay admin-only, exactly like the HTML view it mirrors
        (app.routes.labor_cost.employee_detail).
        """
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee = make_employee(db_session, organization=org, department=department)
        manager = _make_manager(db_session, org, department)
        _login(client, manager)
        start, end = _range()

        response = client.get(
            f"/labor-cost/employees/{employee.id}?start={start}&end={end}&format=csv"
        )

        assert response.status_code == 403

    def test_manager_can_export_department_labor_cost_aggregate(self, client, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        manager = _make_manager(db_session, org, department)
        _login(client, manager)
        start, end = _range()

        response = client.get(
            f"/labor-cost?department_id={department.id}&start={start}&end={end}&format=csv"
        )

        assert response.status_code == 200
        # Rule A4: no per-employee/rate column in the manager-visible
        # aggregate export.
        assert b"Rate" not in response.data

    def test_employee_cannot_export_labor_cost(self, client, db_session):
        org = make_organization(db_session)
        department = make_department(db_session, organization=org)
        employee_record = make_employee(db_session, organization=org, department=department)
        employee_user = make_user(
            db_session,
            organization=org,
            role="employee",
            employee_id=employee_record.id,
            password=PASSWORD,
        )
        _login(client, employee_user)
        start, end = _range()

        response = client.get(
            f"/labor-cost?department_id={department.id}&start={start}&end={end}&format=csv"
        )

        assert response.status_code == 403

    def test_anonymous_user_cannot_export_attendance(self, client):
        response = client.get("/attendance?format=csv")

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


class TestExportCrossOrganizationScope:
    """Same IDOR shape as test_idor_sweep.py: a cross-org id must get a
    plain 404, never a 403 or 500.
    """

    def test_working_hours_export_rejects_foreign_department(self, client, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        other_org = make_organization(db_session)
        foreign_department = make_department(db_session, organization=other_org)
        _login(client, admin)
        start, end = _range()

        response = client.get(
            f"/reports/working-hours?department_id={foreign_department.id}&start={start}&end={end}&format=csv"
        )

        assert response.status_code == 404

    def test_labor_cost_department_export_rejects_foreign_department(self, client, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        other_org = make_organization(db_session)
        foreign_department = make_department(db_session, organization=other_org)
        _login(client, admin)
        start, end = _range()

        response = client.get(
            f"/labor-cost?department_id={foreign_department.id}&start={start}&end={end}&format=csv"
        )

        assert response.status_code == 404

    def test_labor_cost_employee_export_rejects_foreign_employee(self, client, db_session):
        org = make_organization(db_session)
        admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
        other_org = make_organization(db_session)
        other_department = make_department(db_session, organization=other_org)
        foreign_employee = make_employee(db_session, organization=other_org, department=other_department)
        _login(client, admin)
        start, end = _range()

        response = client.get(
            f"/labor-cost/employees/{foreign_employee.id}?start={start}&end={end}&format=csv"
        )

        assert response.status_code == 404
