"""
Integration tier for `ltd admin`: the real dispatch + render path, no container.

The e2e tier (tests/e2e/admin_tui_test.py) drives the DEPLOYED console script
and is the deploy-skew guard. This tier runs the SAME behavior against the
source-tree entry point -- first-party code for real, host filesystem and
process env as the controlled collaborators, nothing mocked, no Docker.

(The file basenames differ across tiers on purpose: pytest imports test modules
by basename and the two roots have no `__init__.py`, so a shared name collides.)

OWN THE PRECONDITION -- "it never touched Docker" is asserted, not assumed: each
cell runs with a PATH scrubbed of `docker`. If `admin` ever leaks back into the
REMAINDER passthrough, ltd hits `check_docker_accessible`, prints its
Docker-not-running banner and exits 1. The cells then fail for that reason, not
by accident.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from curtaincall.expect import expect

pytestmark = pytest.mark.integration

TITLE = "lamp-the-djinn admin"


def _source_ltd() -> str:
    """The venv console script -- the SOURCE-tree artifact this tier owns."""
    ltd = Path(sys.prefix) / "bin" / "ltd"
    if not ltd.exists():
        pytest.skip("project venv has no `ltd` console script (run `uv sync`)")
    return str(ltd)


def _dockerless_env(tmp_path: Path) -> dict[str, str]:
    """A process env whose PATH holds the venv bin and nothing else.

    `docker` is unreachable, so the cage path cannot silently succeed here.
    """
    empty = tmp_path / "bin"
    empty.mkdir(exist_ok=True)
    assert shutil.which("docker", path=str(empty)) is None
    return {**os.environ, "PATH": f"{Path(sys.prefix) / 'bin'}{os.pathsep}{empty}"}


def describe_dispatching_the_admin_subcommand():
    """`ltd admin` renders the admin screen instead of running `admin` in a cage."""

    def it_renders_the_admin_screen_in_a_pty(terminal, tmp_path):
        term = terminal(f"{_source_ltd()} admin", rows=24, cols=80, env=_dockerless_env(tmp_path))

        expect(term.get_by_text(TITLE)).to_be_visible(timeout=20)
        assert term.is_alive, "admin TUI exited the moment it drew its screen"

        term.write("q")
        expect(term).to_have_exited(timeout=10)
        assert term.exit_code == 0, f"admin TUI exited {term.exit_code} on quit"

    def it_prints_the_screen_as_plain_text_when_not_a_tty(tmp_path):
        result = subprocess.run(
            [_source_ltd(), "admin"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_dockerless_env(tmp_path),
            timeout=60,
        )

        assert result.returncode == 0, f"`ltd admin` failed (rc={result.returncode})\n{result.stderr}"
        assert TITLE in result.stdout, f"`ltd admin` printed no screen\n{result.stdout}\n{result.stderr}"

    def it_passes_a_non_bare_admin_command_through_to_the_cage(tmp_path):
        """The reservation is narrow: only a BARE `admin` is the subcommand.

        `ltd admin --status` is a user command named `admin`, so it must take the
        cage path -- which, with no reachable Docker, means a Docker failure and
        a non-zero exit. That failure IS the proof it was not intercepted.
        """
        result = subprocess.run(
            [_source_ltd(), "admin", "--status"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_dockerless_env(tmp_path),
            timeout=60,
        )

        assert TITLE not in result.stdout, "`ltd admin --status` was wrongly intercepted by the admin TUI"
        assert result.returncode != 0
        assert "docker" in result.stderr.lower(), f"expected the cage path to fail on Docker\n{result.stderr}"
