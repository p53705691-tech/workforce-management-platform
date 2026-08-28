"""Settings routes: organization-wide location validation mode and the
job-location catalog — admin only.
"""

import pytest

from tests.factories import make_department, make_employee, make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def _login(client, user):
    return client.post("/login", data={"email": user.email, "password": PASSWORD})


def test_admin_can_view_settings(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.get("/settings")

    assert response.status_code == 200
    assert b"Clock-in/out location validation" in response.data


def test_manager_cannot_view_settings(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.get("/settings")

    assert response.status_code == 403


def test_employee_cannot_view_settings(client, db_session):
    org = make_organization(db_session)
    department = make_department(db_session, organization=org)
    employee_record = make_employee(db_session, organization=org, department=department)
    employee = make_user(
        db_session, organization=org, role="employee", employee_id=employee_record.id, password=PASSWORD
    )
    _login(client, employee)

    response = client.get("/settings")

    assert response.status_code == 403


def test_anonymous_user_cannot_view_settings(client):
    response = client.get("/settings")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_can_change_location_validation_mode(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/settings/location-mode",
        data={"location_validation_mode": "MOBILE"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(org)
    assert org.location_validation_mode == "MOBILE"


def test_invalid_location_validation_mode_is_rejected(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/settings/location-mode",
        data={"location_validation_mode": "NOT_A_REAL_MODE"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db_session.refresh(org)
    assert org.location_validation_mode == "NONE"


def test_admin_can_create_a_job_location(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    _login(client, admin)

    response = client.post(
        "/settings/job-locations",
        data={"name": "Client Site A", "latitude": "10.5", "longitude": "20.5", "radius_meters": "75"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Client Site A" in response.data


def test_manager_cannot_create_a_job_location(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    _login(client, manager)

    response = client.post(
        "/settings/job-locations",
        data={"name": "Client Site A", "latitude": "10.5", "longitude": "20.5", "radius_meters": "75"},
    )

    assert response.status_code == 403
