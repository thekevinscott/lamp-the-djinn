"""
Unit tests for resolve_command: what argv actually runs inside the cage.

Style is pytest-describe (describe_/it_ blocks).
"""

import pytest

from lamp_the_djinn.command import resolve_command

pytestmark = pytest.mark.unit


def describe_resolve_command():
    """Precedence: explicit command > --shell > default claude."""

    def it_prefers_an_explicit_command():
        assert resolve_command(["claude", "-p", "hi"], "echo no", False) == ["claude", "-p", "hi"]

    def it_falls_back_to_default_claude():
        """Bare ltd (no command, no shell) defaults to skip-permissions claude."""
        assert resolve_command([], None, False) == ["claude", "--dangerously-skip-permissions"]

    def it_uses_plain_claude_in_safe_mode():
        """--safe-mode drops the skip-permissions flag."""
        assert resolve_command([], None, True) == ["claude"]

    def it_maps_shell_to_bash_c():
        """--shell CMD is equivalent to bash -c CMD when no command is given."""
        assert resolve_command([], "cat /workspace/x", False) == ["bash", "-c", "cat /workspace/x"]

    def it_splits_a_single_quoted_whitespace_command():
        """A command quoted as ONE token (`ltd '... npx -y pkg ...'`) arrives as a
        single argv element with spaces; `devcontainer exec` would treat the whole
        string as one executable name and fail, so we shlex-split it back to argv."""
        assert resolve_command(["npx -y @earendil-works/pi-coding-agent"], None, False) == [
            "npx",
            "-y",
            "@earendil-works/pi-coding-agent",
        ]

    def it_leaves_a_single_bare_token_untouched():
        """A lone token with no whitespace (`ltd claude`) is already valid argv --
        do not shlex-split it (that would just rebuild the same single element)."""
        assert resolve_command(["claude"], None, False) == ["claude"]
