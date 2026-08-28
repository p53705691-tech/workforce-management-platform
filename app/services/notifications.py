"""Email notifications: a single entry point for outbound email.

Mirrors ``app.services.audit``'s "one entry point, no ad-hoc
construction" discipline (see that module's docstring): every
notification in this codebase is sent through ``send_email`` — no route
or service ever imports ``smtplib``/builds an ``EmailMessage`` directly
elsewhere.

Unlike ``audit.record``, a notification send is never part of the
caller's database transaction. Email delivery is best-effort: a slow or
unreachable SMTP server must never block, delay, or roll back a primary
business action (approving leave must succeed even if the email
announcing it fails to send). Every call site in this codebase calls
``send_email`` strictly *after* its own ``db.session.commit()`` has
already succeeded — never before it, and never inside the same
transaction.

``MAIL_BACKEND`` (``app.config``) selects delivery:

- ``"console"`` — log the rendered email instead of sending (the
  ``DevelopmentConfig`` default), so local development needs no SMTP
  server.
- ``"suppress"`` — do nothing at all (the ``TestingConfig`` default), so
  the test suite never performs real network I/O.
- ``"smtp"`` — send for real via stdlib ``smtplib``, using
  ``SMTP_HOST``/``SMTP_PORT``/``SMTP_USERNAME``/``SMTP_PASSWORD``/
  ``SMTP_USE_TLS``/``MAIL_FROM_ADDRESS`` from the environment (see
  ``app.config``). Required in ``ProductionConfig``, which fails fast at
  boot if ``SMTP_HOST``/``MAIL_FROM_ADDRESS`` are missing — the same
  "fail fast on a missing secret/setting" pattern already used for
  ``SECRET_KEY``/``DATABASE_URL``.

A send failure (connection error, auth failure, timeout, malformed
address, ...) is caught here, logged, and never raised into the caller:
by the time this runs the caller has already committed its primary
write, so there is nothing left to roll back and no reason to interrupt
the request.
"""

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app, render_template

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, template_name: str, **context) -> None:
    """Render and send one email. Best-effort: never raises.

    ``template_name`` names a pair of templates under
    ``templates/emails/``: ``emails/<template_name>.txt`` and
    ``emails/<template_name>.html``. Both are rendered and sent as a
    multipart message — every email needs a working plain-text body,
    since some recipients/clients never render HTML (per this
    milestone's explicit constraint).
    """
    backend = current_app.config.get("MAIL_BACKEND", "suppress")
    if backend == "suppress":
        return

    text_body = render_template(f"emails/{template_name}.txt", **context)
    html_body = render_template(f"emails/{template_name}.html", **context)

    if backend == "console":
        current_app.logger.info(
            "Email suppressed by console backend (dev mode) — To: %s | "
            "Subject: %s\n%s",
            to,
            subject,
            text_body,
        )
        return

    if backend != "smtp":
        logger.error("Unknown MAIL_BACKEND %r; email not sent.", backend)
        return

    _send_via_smtp(to, subject, text_body, html_body)


def _send_via_smtp(to: str, subject: str, text_body: str, html_body: str) -> None:
    """Send one already-rendered email over SMTP. Never raises.

    Every failure mode here (missing configuration, connection refused,
    authentication failure, timeout) is caught and logged rather than
    propagated — see the module docstring on why a notification send
    must never be allowed to interrupt the caller's already-committed
    primary action.
    """
    config = current_app.config
    from_address = config.get("MAIL_FROM_ADDRESS")
    host = config.get("SMTP_HOST")
    if not from_address or not host:
        logger.error(
            "SMTP_HOST/MAIL_FROM_ADDRESS is not configured; email to %s not sent.",
            to,
        )
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    port = config.get("SMTP_PORT") or 587
    username = config.get("SMTP_USERNAME")
    password = config.get("SMTP_PASSWORD")
    use_tls = config.get("SMTP_USE_TLS", True)

    try:
        with smtplib.SMTP(host, port, timeout=10) as client:
            if use_tls:
                client.starttls()
            if username and password:
                client.login(username, password)
            client.send_message(message)
    except Exception:
        # Caught broadly and deliberately: any smtplib/socket/OSError
        # here means "the email didn't go out," which is always
        # recoverable from the caller's point of view (the primary
        # write already committed) and never a reason to surface a 500.
        logger.exception("Failed to send email to %s via SMTP", to)
