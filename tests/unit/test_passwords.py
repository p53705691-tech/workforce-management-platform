import pytest

from app.auth.passwords import hash_password, verify_password

pytestmark = pytest.mark.unit


def test_hash_and_verify_round_trip():
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password(hashed, "correct horse battery staple") is True


def test_verify_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")

    assert verify_password(hashed, "wrong password") is False


def test_hash_is_salted_and_therefore_not_deterministic():
    first = hash_password("same input")
    second = hash_password("same input")

    assert first != second
    assert verify_password(first, "same input") is True
    assert verify_password(second, "same input") is True
