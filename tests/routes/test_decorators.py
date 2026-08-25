"""Route-level coverage for ``role_required``.

Exercises the decorator through a real HTTP request against the
``/__test/admin-only`` route registered in ``conftest.py`` (``role_required``
isn't wired into any real M1 route yet — no route needs a role restriction
until M2's department/employee CRUD).
"""

import pytest

from tests.factories import make_organization, make_user

pytestmark = pytest.mark.route

PASSWORD = "correct horse battery staple"


def test_anonymous_request_redirects_to_login(client):
    response = client.get("/__test/admin-only")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_wrong_role_is_forbidden(client, db_session):
    org = make_organization(db_session)
    manager = make_user(db_session, organization=org, role="manager", password=PASSWORD)
    client.post("/login", data={"email": manager.email, "password": PASSWORD})

    response = client.get("/__test/admin-only")

    assert response.status_code == 403


def test_matching_role_is_allowed(client, db_session):
    org = make_organization(db_session)
    admin = make_user(db_session, organization=org, role="admin", password=PASSWORD)
    client.post("/login", data={"email": admin.email, "password": PASSWORD})

    response = client.get("/__test/admin-only")

    assert response.status_code == 200
    assert response.data == b"ok"
