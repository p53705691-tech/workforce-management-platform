"""Shared service-layer exceptions.

``ValidationError`` is how a service reports a business-rule violation
that isn't an authorization failure (those use ``flask.abort``) — routes
catch it and turn it into a user-facing message instead of a raw 500 or
an unhandled database exception.
"""


class ValidationError(Exception):
    """A service-layer input failed a business validation rule.

    ``field`` is optional and only set when the error is attributable to
    a single form field, so a route can attach it to that field instead
    of showing it as a generic message.
    """

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
