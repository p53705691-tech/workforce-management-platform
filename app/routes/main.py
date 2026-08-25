"""Root landing route.

``main.index`` is ``app.routes.auth.DEFAULT_LANDING_ENDPOINT`` — the
post-login redirect target and the concrete ``login_required``-protected
route exercised by the login-flow tests, which assert the literal ``/``
redirect path. Rather than rendering its own placeholder page (M0-M7),
it now hands off to the real post-login landing page introduced in M8,
``dashboard.index`` — an unauthenticated request is still redirected to
the login page by ``login_required`` before this ever runs, so the
existing "logged-out GET / redirects to /login" behavior is unchanged.
"""

from flask import Blueprint, redirect, url_for

from app.auth.decorators import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    return redirect(url_for("dashboard.index"))
