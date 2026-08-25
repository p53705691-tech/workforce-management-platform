"""Login and logout routes.

Business logic (credential checking, lockout) lives in
``app.auth.service``; this module only handles the HTTP concerns (form
handling, session/cookie lifecycle, redirects).
"""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from app.auth.decorators import login_required
from app.auth.redirects import get_safe_redirect_target
from app.auth.service import authenticate
from app.forms import LoginForm

auth_bp = Blueprint("auth", __name__)

DEFAULT_LANDING_ENDPOINT = "main.index"


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(DEFAULT_LANDING_ENDPOINT))

    form = LoginForm()

    if form.validate_on_submit():
        result = authenticate(form.email.data.strip(), form.password.data)

        if result.success:
            # Discard any pre-authentication session state (including the
            # CSRF token already validated above) before establishing the
            # authenticated session, so nothing set before login carries
            # over into it (session fixation defense).
            session.clear()
            # Marks the cookie as subject to PERMANENT_SESSION_LIFETIME
            # (app.config) instead of expiring only when the browser
            # closes, so a stolen/idle session cookie has a real absolute
            # expiry rather than none.
            session.permanent = True
            login_user(result.user)

            next_target = get_safe_redirect_target(
                request.args.get("next"), url_for(DEFAULT_LANDING_ENDPOINT)
            )
            return redirect(next_target)

        flash(result.error, "error")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
