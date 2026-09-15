"""
Unit tests for apply_env_defaults: the LTD_* environment fills options the user
did not pass on the command line.

The namespace is built here rather than by create_parser: a unit test isolates
its unit, and the parser's own defaults are pinned in parser_test.py.

Style is pytest-describe (describe_/it_ blocks).
"""

import argparse
from unittest import mock

import pytest

from lamp_the_djinn.env_defaults import apply_env_defaults

pytestmark = pytest.mark.unit


def _unset_args(**overrides) -> argparse.Namespace:
    """Every option at its "user passed nothing" value, so the env decides."""
    base = dict(
        ssh_key_file=None,
        git_user_name=None,
        git_user_email=None,
        gh_token=None,
        gpg_key_id=None,
        model=None,
        proxy_url=None,
        runtime=None,
        debug=False,
        trusted=False,
        memory=None,
        allow_domains_file=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def describe_trusted_flag_and_env():
    """--trusted is opt-in; LTD_TRUSTED opts in too."""

    def it_leaves_trusted_false_without_the_env():
        args = _unset_args()
        with mock.patch.dict("os.environ", {}, clear=True):
            apply_env_defaults(args)
        assert args.trusted is False

    def it_reads_trusted_from_env():
        args = _unset_args()
        with mock.patch.dict("os.environ", {"LTD_TRUSTED": "1"}, clear=False):
            apply_env_defaults(args)
        assert args.trusted is True

    def it_never_unsets_an_explicit_flag():
        """A --trusted run stays trusted even with no env set."""
        args = _unset_args(trusted=True)
        with mock.patch.dict("os.environ", {}, clear=True):
            apply_env_defaults(args)
        assert args.trusted is True


def describe_memory_env():
    """The per-cage cap can arrive from the environment."""

    def it_reads_memory_from_env():
        args = _unset_args()
        with mock.patch.dict("os.environ", {"LTD_MEMORY": "4g"}, clear=False):
            apply_env_defaults(args)
        assert args.memory == "4g"


def describe_allow_domains_file_env():
    """The per-run egress allowlist file can also arrive via the environment."""

    def it_reads_allow_domains_file_from_env():
        args = _unset_args()
        with mock.patch.dict("os.environ", {"LTD_ALLOW_DOMAINS_FILE": "/some/path.txt"}, clear=False):
            apply_env_defaults(args)
        assert args.allow_domains_file == "/some/path.txt"


def describe_resolved_defaults():
    """Some options coalesce to a literal default rather than staying unset."""

    def it_defaults_the_model_to_local():
        args = _unset_args()
        with mock.patch.dict("os.environ", {}, clear=True):
            apply_env_defaults(args)
        assert args.model == "local"

    def it_defaults_the_runtime_to_auto():
        args = _unset_args()
        with mock.patch.dict("os.environ", {}, clear=True):
            apply_env_defaults(args)
        assert args.runtime == "auto"

    def it_defaults_the_proxy_key_to_the_project_placeholder():
        args = _unset_args()
        with mock.patch.dict("os.environ", {}, clear=True):
            apply_env_defaults(args)
        assert args.proxy_api_key == "lamp-the-djinn"
