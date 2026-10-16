"""
Integration tests for boolean LTD_* environment variables.

The real parser and apply_env_defaults run against the real process
environment, the way `LTD_TRUSTED=false ltd` reaches them. The env is set with
patch.dict inside a fixture so it is scoped and restored on teardown.
"""

from collections.abc import Callable, Iterator
from unittest import mock

import pytest

from lamp_the_djinn.env_defaults import apply_env_defaults
from lamp_the_djinn.parser import create_parser

pytestmark = pytest.mark.integration


@pytest.fixture
def resolve_with_env() -> Iterator[Callable]:
    """Resolve ltd's args with exactly the given LTD_* env and no other."""

    def resolve(env: dict[str, str]):
        with mock.patch.dict("os.environ", env, clear=True):
            args = create_parser().parse_args([])
            apply_env_defaults(args)
        return args

    yield resolve


def describe_ltd_trusted():
    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def it_stays_untrusted_for_a_falsey_value(resolve_with_env, value):
        assert resolve_with_env({"LTD_TRUSTED": value}).trusted is False

    def it_turns_trusted_on_for_true(resolve_with_env):
        assert resolve_with_env({"LTD_TRUSTED": "true"}).trusted is True


def describe_ltd_debug():
    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def it_stays_quiet_for_a_falsey_value(resolve_with_env, value):
        assert resolve_with_env({"LTD_DEBUG": value}).debug is False
