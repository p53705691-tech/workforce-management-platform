"""Route decorators for authentication and role-based authorization.

``login_required`` re-exports Flask-Login's decorator so route modules
have a single import path (``app.auth.decorators``) for both
authentication and role checks. Flask-Login redirects unauthenticated
requests to ``login_manager.login_view`` with a same-site ``next``
(``request.url``, generated server-side, not attacker input) — the actual
open-redirect risk lives in how the login route re-reads that ``next``
value, handled separately by ``app.auth.redirects``.
"""

from functools import wraps

from flask import abort
from flask_login import current_user
from flask_login import login_required as _flask_login_required

login_required = _flask_login_required


def role_required(*roles: str):
    """Require the current user to hold one of ``roles``.

    Implies ``login_required``: an unauthenticated request is redirected
    to the login page before the role check ever runs.
    """

    def decorator(view):
        @wraps(view)
        @_flask_login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator
