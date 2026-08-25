import pytest

from app.auth.redirects import get_safe_redirect_target

pytestmark = pytest.mark.unit


def test_relative_path_is_returned_as_is():
    assert get_safe_redirect_target("/dashboard", "/") == "/dashboard"


def test_relative_path_with_query_string_is_returned_as_is():
    assert get_safe_redirect_target("/dashboard?tab=1", "/") == "/dashboard?tab=1"


def test_missing_candidate_falls_back_to_default():
    assert get_safe_redirect_target(None, "/") == "/"
    assert get_safe_redirect_target("", "/") == "/"


def test_absolute_url_is_rejected():
    assert get_safe_redirect_target("https://evil.example/phish", "/") == "/"


def test_protocol_relative_url_is_rejected():
    assert get_safe_redirect_target("//evil.example/phish", "/") == "/"


def test_scheme_relative_without_leading_slash_is_rejected():
    assert get_safe_redirect_target("evil.example/phish", "/") == "/"


def test_backslash_prefixed_url_is_rejected():
    # Browsers treat `\` like `/` when resolving a relative reference, so
    # `/\evil.example` resolves to `https://evil.example/` even though
    # urlsplit sees no scheme/netloc and a leading "/".
    assert get_safe_redirect_target("/\\evil.example", "/") == "/"


def test_double_backslash_url_is_rejected():
    assert get_safe_redirect_target("\\\\evil.example", "/") == "/"


def test_slash_backslash_slash_url_is_rejected():
    assert get_safe_redirect_target("/\\/evil.example", "/") == "/"
