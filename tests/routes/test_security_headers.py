"""Route-level coverage for the baseline security response headers added
by ``app.create_app``'s ``after_request`` hook.
"""

import pytest

pytestmark = pytest.mark.route


def test_response_includes_baseline_hardening_headers(client):
    response = client.get("/login")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_response_includes_a_strict_content_security_policy(client):
    response = client.get("/login")

    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'self'" in csp
    assert "object-src 'none'" in csp


def test_oversized_request_body_is_rejected_with_413(client, app):
    oversized_body = b"a" * (app.config["MAX_CONTENT_LENGTH"] + 1)

    response = client.post(
        "/login",
        data=oversized_body,
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 413


def test_hsts_header_is_absent_when_session_cookie_secure_is_false(client, app):
    # TestingConfig sets SESSION_COOKIE_SECURE = False (see app/config.py):
    # sending HSTS to a client that could be talking to this app over
    # plain HTTP would actively break it, so the header must be genuinely
    # conditional on this setting, not merely present unconditionally.
    assert app.config["SESSION_COOKIE_SECURE"] is False

    response = client.get("/login")

    assert "Strict-Transport-Security" not in response.headers


def test_hsts_header_is_present_when_session_cookie_secure_is_true(client, app):
    app.config["SESSION_COOKIE_SECURE"] = True
    try:
        response = client.get("/login")
        assert (
            response.headers["Strict-Transport-Security"]
            == "max-age=31536000; includeSubDomains"
        )
    finally:
        app.config["SESSION_COOKIE_SECURE"] = False
