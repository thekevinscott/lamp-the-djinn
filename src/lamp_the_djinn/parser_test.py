"""
Unit tests for create_parser: REMAINDER splits ltd's own options from the
in-cage command, so the command's own flags are never stolen.

Style is pytest-describe (describe_/it_ blocks).
"""

import pytest

from lamp_the_djinn.parser import create_parser

pytestmark = pytest.mark.unit


def describe_command_parsing():
    """REMAINDER splits ltd's own options from the in-cage command."""

    def it_splits_ltd_opts_from_command():
        """ltd options before the command are parsed; the rest is the command."""
        parser = create_parser()
        args = parser.parse_args(["--model", "glm-5.2", "claude", "-p", "hi"])
        assert args.model == "glm-5.2"
        # The command's own -p is NOT stolen by ltd's -p/--port.
        assert args.command == ["claude", "-p", "hi"]
        assert args.port is None

    def it_treats_bare_runner_as_the_command():
        """A command with no leading ltd options is captured verbatim."""
        parser = create_parser()
        args = parser.parse_args(["npx", "@anthropic/claude"])
        assert args.command == ["npx", "@anthropic/claude"]

    def it_passes_harness_resume_flags_through():
        """pi's -c/--continue survives REMAINDER untouched (ltd pi -c)."""
        parser = create_parser()
        args = parser.parse_args(["pi", "--continue"])
        assert args.command == ["pi", "--continue"]

    def it_does_not_steal_command_flags_matching_ltd_flags():
        """ltd's -p stops at the first command token; later -p belongs to the command."""
        parser = create_parser()
        args = parser.parse_args(["-p", "8080", "claude", "-p", "prompt"])
        # ltd's own -p captured the port; the command keeps its own -p.
        assert args.port == ["8080"]
        assert args.command == ["claude", "-p", "prompt"]

    def it_leaves_command_empty_when_only_ltd_opts_given():
        """With no command tokens, command is empty (default applies later)."""
        parser = create_parser()
        args = parser.parse_args(["--safe-mode"])
        assert args.command == []
        assert args.safe_mode is True

    def it_has_no_harness_flag():
        """The named --harness flag was removed."""
        parser = create_parser()
        # Unknown option -> parser errors (SystemExit), proving it is gone.
        try:
            parser.parse_args(["--harness", "codex"])
        except SystemExit:
            pass
        else:  # pragma: no cover - guard
            raise AssertionError("--harness should no longer be a recognized flag")


def describe_trust_tier_flag():
    """--trusted is opt-in: strict ~/.claude exposure is the default."""

    def it_defaults_trusted_false():
        parser = create_parser()
        args = parser.parse_args([])
        assert args.trusted is False

    def it_sets_trusted_from_flag():
        parser = create_parser()
        args = parser.parse_args(["--trusted"])
        assert args.trusted is True
