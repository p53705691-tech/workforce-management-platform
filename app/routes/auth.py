"""Login and logout routes.

Business logic (credential checking, lockout) lives in
``app.auth.service``; this module only handles the HTTP concerns (form
handling, session/cookie lifecycle, redirects).
"""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from app.auth.decorators import login_required
from app.auth.redirects import get_safe_redirect_target
from app.auth.service import (
    GENERIC_RESET_REQUESTED_MESSAGE,
    authenticate,
    change_password,
    request_password_reset,
    reset_password,
)
from app.extensions import limiter
from app.forms import ChangePasswordForm, ForgotPasswordForm, LoginForm, ResetPasswordForm
from app.services.errors import ValidationError

auth_bp = Blueprint("auth", __name__)

DEFAULT_LANDING_ENDPOINT = "main.index"


@auth_bp.route("/login", methods=["GET", "POST"])
# Per-IP only — see app.extensions.limiter's docstring for what this
# does and does not protect against. Applies only to the POST (the
# actual credential-checking, Argon2-costing request); viewing the
# login page itself is never throttled.
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
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
            # Stamped into the session so load_user can detect a password
            # change that happened after this session was established —
            # see that function's docstring for why this is the actual
            # enforcement point, same mechanism already used for
            # is_active/locked_until.
            session["pwd_changed_at"] = result.user.password_changed_at.isoformat()

            next_target = get_safe_redirect_target(
                request.args.get("next"), url_for(DEFAULT_LANDING_ENDPOINT)
            )
            return redirect(next_target)

        flash(result.error, "error")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/account", methods=["GET"])
@login_required
def account():
    """A minimal, role-agnostic account page whose only purpose is
    exposing ``change_password_route`` to every role.

    Before this route existed, ``ChangePasswordForm`` was only ever
    rendered on the employee-only Profile page (see
    ``app.routes.employees.my_profile``) even though the change-password
    route itself is deliberately not role-restricted — an admin or
    manager had no reachable page to rotate their own password at all
    (security-review finding). An employee still uses their own Profile
    page (linked from the sidebar); this page is linked from the topbar
    user menu for admin/manager only, so each role has exactly one
    reachable place to do this, never two.
    """
    return render_template("auth/account.html", password_form=ChangePasswordForm())


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
# Same per-IP throttle as /login's POST — this path also triggers a real
# email send plus a DB write on every valid submission, and is otherwise
# unauthenticated and open to anyone.
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for(DEFAULT_LANDING_ENDPOINT))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        request_password_reset(form.email.data.strip())
        # Always the same message regardless of whether the email
        # matched a real account — see
        # app.auth.service.request_password_reset's docstring.
        flash(GENERIC_RESET_REQUESTED_MESSAGE, "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_route(token):
    if current_user.is_authenticated:
        return redirect(url_for(DEFAULT_LANDING_ENDPOINT))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            reset_password(token, form.new_password.data)
            flash("Your password has been reset. Sign in with your new password.", "success")
            return redirect(url_for("auth.login"))
        except ValidationError as error:
            flash(error.message, "error")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form, token=token)


@auth_bp.route("/change-password", methods=["POST"])
@login_required
def change_password_route():
    """Self-service password change. Not tied to the Employee Profile
    page specifically (any signed-in role may change their own
    password) even though that page is, today, the only UI that renders
    this form — redirecting to the dashboard keeps this route correct
    for every role rather than a page only employees can reach.
    """
    form = ChangePasswordForm()
    if form.validate_on_submit():
        try:
            change_password(
                current_user, form.current_password.data, form.new_password.data
            )
            # Refresh this session's own stamp to the new value
            # immediately — otherwise load_user (see its docstring on
            # password_changed_at) would treat this very session as
            # stale on the very next request and sign the user who just
            # changed their own password straight back out.
            session["pwd_changed_at"] = current_user.password_changed_at.isoformat()
            flash("Password changed.", "success")
        except ValidationError as error:
            flash(error.message, "error")
    else:
        flash("Please correct the errors and try again.", "error")

    return redirect(url_for("dashboard.index"))
