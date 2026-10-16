"""Unit tests for first_non_flag: the package-spec scan behind record_manifest."""

from typing import get_type_hints

import pytest

from lamp_the_djinn.first_non_flag import first_non_flag

pytestmark = pytest.mark.unit


def describe_first_non_flag():
    """The first token that is not a flag, or None."""

    def it_returns_the_first_bare_token():
        assert first_non_flag(["pkg", "other"]) == "pkg"

    def it_skips_leading_flags():
        assert first_non_flag(["-y", "--quiet", "pkg"]) == "pkg"

    def it_returns_none_for_flags_only():
        assert first_non_flag(["-y", "--quiet"]) is None

    def it_returns_none_for_an_empty_list():
        assert first_non_flag([]) is None

    def it_skips_the_value_of_an_option_that_takes_one():
        assert first_non_flag(["--registry", "http://x", "pkg"]) == "pkg"

    def it_skips_a_uv_option_value():
        assert first_non_flag(["--python", "3.12", "ruff"]) == "ruff"

    def it_returns_the_value_of_a_package_option():
        assert first_non_flag(["-p", "left-pad", "left-pad-bin"], {"-p"}) == "left-pad"

    def it_returns_the_value_of_an_inline_package_option():
        assert first_non_flag(["--from=httpie", "http"], {"--from"}) == "httpie"

    def it_returns_none_for_a_trailing_package_option():
        assert first_non_flag(["--from"], {"--from"}) is None

    def it_declares_an_optional_str_return():
        assert get_type_hints(first_non_flag)["return"] == str | None
