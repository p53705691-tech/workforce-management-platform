"""Flask error handlers.

The 500 handler logs the underlying exception server-side but only ever
returns a generic message to the client. Stack traces and other internal
details must never reach the browser.
"""

import logging

from flask import render_template

logger = logging.getLogger(__name__)


def handle_bad_request(error):
    return render_template("errors/400.html"), 400


def handle_forbidden(error):
    return render_template("errors/403.html"), 403


def handle_not_found(error):
    return render_template("errors/404.html"), 404


def handle_payload_too_large(error):
    return render_template("errors/413.html"), 413


def handle_internal_server_error(error):
    logger.exception("Unhandled exception while processing request")
    return render_template("errors/500.html"), 500


def register_error_handlers(app):
    app.register_error_handler(400, handle_bad_request)
    app.register_error_handler(403, handle_forbidden)
    app.register_error_handler(404, handle_not_found)
    app.register_error_handler(413, handle_payload_too_large)
    app.register_error_handler(500, handle_internal_server_error)
