"""Unit tests for first_non_flag: the package-spec scan behind record_manifest."""

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
