"""
End-to-end test for `ltd admin`: a TUI screen in a real PTY.

WHAT IS PINNED
    `ltd admin` opens a full-screen admin view ON THE HOST -- it must render a
    title, stay alive, and exit cleanly on `q`, restoring the terminal. It must
    NOT be swallowed by the REMAINDER passthrough and shipped off to a cage.

DEPLOY SKEW -- same discipline as tests/e2e/coding_agent_test.py: we drive the
installed `ltd` CONSOLE SCRIPT through a real PTY, never `uv run` against
`src/`, and we print which artifact ran. A TUI is exactly the kind of change
that can look right in source and be broken in the shipped entry point (missing
module in the wheel, console-script stdio differences).

NO DOCKER -- unlike the other e2e cells, this one needs no container: `ltd
admin` is host-side by design. The test asserts that directly, by failing if the
screen shows cage/devcontainer plumbing.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from curtaincall.expect import expect

pytestmark = pytest.mark.e2e

TITLE = "lamp-the-djinn admin"

# Noise that only appears when ltd took the CAGE path -- i.e. `admin` leaked
# through the REMAINDER passthrough instead of being handled on the host.
CAGE_MARKERS = ("devcontainer", "docker", "pulling", "cage")


def _ltd_binary() -> str | None:
    """Resolve the DEPLOYED `ltd`, excluding the venv shadow. See coding_agent_test.py."""
    override = os.environ.get("LTD_BIN")
    if override:
        return override
    venv_bin = (Path(sys.prefix) / "bin").resolve()
    search = os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p).resolve() != venv_bin
    )
    return shutil.which("ltd", path=search) or shutil.which("lamp-the-djinn", path=search)


def _require_ltd() -> str:
    ltd = _ltd_binary()
    if ltd is None:
        pytest.skip("ltd/lamp-the-djinn console script not installed on PATH (set LTD_BIN)")
    print(f"\n[e2e] exercising deployed artifact: {ltd}")
    return ltd


def describe_opening_the_admin_tui():
    """`ltd admin` opens a host-side TUI and quits cleanly."""

    def it_renders_the_admin_screen_in_a_pty(terminal):
        ltd = _require_ltd()

        term = terminal(f"{ltd} admin", rows=24, cols=80)

        expect(term.get_by_text(TITLE)).to_be_visible(timeout=30)
        assert term.is_alive, "admin TUI exited the moment it drew its screen"

        # Host-side means host-side: no cage was built or entered.
        buffer = "\n".join("".join(row) for row in term.get_buffer()).lower()
        leaked = next((m for m in CAGE_MARKERS if m in buffer), None)
        assert leaked is None, f"`ltd admin` took the cage path -- saw {leaked!r} on screen"

        # `q` quits, and the process ends cleanly rather than being killed.
        term.write("q")
        expect(term).to_have_exited(timeout=10)
        assert term.exit_code == 0, f"admin TUI exited {term.exit_code} on quit"

    def it_prints_the_screen_as_plain_text_when_not_a_tty():
        """Piped (`ltd admin | cat`) must print once and exit, never hang on a key read."""
        ltd = _require_ltd()

        result = subprocess.run(
            [ltd, "admin"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, f"piped `ltd admin` failed (rc={result.returncode})\n{result.stderr}"
        assert TITLE in result.stdout, f"piped `ltd admin` printed no screen\n{result.stdout}\n{result.stderr}"
