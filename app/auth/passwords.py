"""Password hashing, isolated behind a small wrapper around argon2-cffi.

Centralizing this here means the hashing algorithm/parameters can change
in one place without touching every caller, and callers never need to
import ``argon2`` directly or handle its exceptions themselves.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a plaintext password for storage."""
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    """Return True if ``plain`` matches ``password_hash``.

    Only a mismatched password is treated as "verification failed"
    (returns False). Any other failure (a corrupt/unrecognized hash, for
    example) is unexpected and is allowed to propagate rather than being
    silently swallowed into a generic "login failed" result.
    """
    try:
        return _hasher.verify(password_hash, plain)
    except VerifyMismatchError:
        return False
