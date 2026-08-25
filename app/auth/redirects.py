"""Open-redirect guard for post-login ``next`` targets.

Flask-Login's own redirect-to-login mechanism embeds a same-site URL, so
the actual attack surface is the ``next`` value coming back on the login
form submission: an attacker can craft ``/login?next=https://evil.example``
and hope a successful login blindly redirects there.
"""

from urllib.parse import urlsplit


def get_safe_redirect_target(candidate: str | None, default: str) -> str:
    """Return ``candidate`` if it is a safe same-site relative path.

    Rejects anything carrying a scheme (``https://evil.example``) or a
    network location, including protocol-relative URLs
    (``//evil.example``), falling back to ``default`` instead.

    Browsers (per the WHATWG URL spec) treat ``\\`` identically to ``/``
    when resolving a relative reference, so ``/\\evil.example`` resolves
    to ``https://evil.example/`` even though ``urlsplit`` sees no
    scheme/netloc and a leading ``/``. Reject any candidate containing a
    backslash outright, and also normalize backslashes to forward
    slashes before parsing so the existing scheme/netloc/``//`` checks
    catch the browser-resolved form too.
    """
    if not candidate:
        return default

    if "\\" in candidate:
        return default

    normalized = candidate.replace("\\", "/")

    parts = urlsplit(normalized)
    if parts.scheme or parts.netloc:
        return default
    if not normalized.startswith("/") or normalized.startswith("//"):
        return default

    return candidate
