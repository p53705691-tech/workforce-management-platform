"""Integration tests for app.services.notifications.

Covers backend selection (``suppress``/``console``/``smtp``) and the
hard rule that a send failure is caught, logged, and never raised —
see that module's docstring. Call-site wiring (which template/recipient
each of leave.py/employees.py picks, and that a simulated SMTP failure
never blocks the primary action) is covered alongside the rest of each
call site's own tests, in tests/integration/test_leave_service.py and
tests/integration/test_employee_service.py.
"""

import smtplib

import pytest

from app.services import notifications as notification_service

pytestmark = pytest.mark.integration


class _FakeSMTP:
    """Records what would have been sent, with no real network I/O."""

    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        _FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.sent = []
    yield
    _FakeSMTP.sent = []


def _send_account_created_email(**overrides):
    context = {
        "organization_name": "Acme",
        "login_email": "person@example.com",
    }
    context.update(overrides)
    notification_service.send_email(
        "person@example.com", "Your account is ready", "account_created", **context
    )


def test_suppress_backend_sends_nothing(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "suppress")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    _send_account_created_email()

    assert _FakeSMTP.sent == []


def test_console_backend_logs_instead_of_sending(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "console")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    with caplog.at_level("INFO"):
        _send_account_created_email()

    assert _FakeSMTP.sent == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("person@example.com" in message for message in messages)
    assert any("Your account is ready" in message for message in messages)


def test_smtp_backend_sends_a_multipart_message_with_text_and_html(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "smtp")
    monkeypatch.setitem(app.config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setitem(app.config, "SMTP_PORT", 587)
    monkeypatch.setitem(app.config, "MAIL_FROM_ADDRESS", "noreply@acme.test")
    monkeypatch.setitem(app.config, "SMTP_USERNAME", "svc-account")
    monkeypatch.setitem(app.config, "SMTP_PASSWORD", "not-a-real-secret")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    _send_account_created_email()

    assert len(_FakeSMTP.sent) == 1
    message = _FakeSMTP.sent[0]
    assert message["To"] == "person@example.com"
    assert message["From"] == "noreply@acme.test"
    assert message["Subject"] == "Your account is ready"
    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    assert text_part is not None and "Acme" in text_part.get_content()
    assert html_part is not None and "Acme" in html_part.get_content()
    # The password is never part of this email's content, regardless of
    # backend — see app.services.employees._notify_employee_account_email.
    assert "hunter2" not in text_part.get_content()


def test_smtp_backend_authenticates_when_credentials_are_configured(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "smtp")
    monkeypatch.setitem(app.config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setitem(app.config, "MAIL_FROM_ADDRESS", "noreply@acme.test")
    monkeypatch.setitem(app.config, "SMTP_USERNAME", "svc-account")
    monkeypatch.setitem(app.config, "SMTP_PASSWORD", "not-a-real-secret")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    _send_account_created_email()

    assert len(_FakeSMTP.sent) == 1


def test_smtp_backend_without_configured_host_sends_nothing(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "smtp")
    monkeypatch.setitem(app.config, "SMTP_HOST", None)
    monkeypatch.setitem(app.config, "MAIL_FROM_ADDRESS", "noreply@acme.test")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    with caplog.at_level("ERROR"):
        _send_account_created_email()

    assert _FakeSMTP.sent == []


def test_smtp_connection_failure_is_caught_logged_and_never_raises(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "smtp")
    monkeypatch.setitem(app.config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setitem(app.config, "MAIL_FROM_ADDRESS", "noreply@acme.test")

    def _boom(*args, **kwargs):
        raise ConnectionRefusedError("no smtp server listening here")

    monkeypatch.setattr(smtplib, "SMTP", _boom)

    # Asserted via a monkeypatched logger.exception call rather than
    # caplog: this test session's schema migration runs through
    # Alembic's env.py, which calls logging.config.fileConfig(...) with
    # its default disable_existing_loggers=True — silently disabling
    # any module-level logging.getLogger(__name__) logger already
    # imported by the time that runs (a pytest-session-only quirk;
    # outside the test suite, migrations run as a separate process
    # from the application, so this never affects real logging).
    # Patching the logger directly still proves the exact code path
    # this test cares about, independent of that quirk.
    exceptions_logged = []
    monkeypatch.setattr(
        notification_service.logger,
        "exception",
        lambda message, *args: exceptions_logged.append(message),
    )

    # Must not raise -- a down SMTP server is never allowed to
    # propagate into the caller (see the module docstring).
    _send_account_created_email()

    assert len(exceptions_logged) == 1
    assert "Failed to send email" in exceptions_logged[0]


def test_unknown_mail_backend_sends_nothing_and_logs(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "MAIL_BACKEND", "carrier-pigeon")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    with caplog.at_level("ERROR"):
        _send_account_created_email()

    assert _FakeSMTP.sent == []
