"""
End-to-end regression test for the base case: spinning up a coding agent.

This reproduces the exact user-reported failure, byte for byte:

    $ ltd npx -y @earendil-works/pi-coding-agent
    npm error code EROFS
    npm error path /home/node/.cache/ltd-harness/npm/_cacache/tmp/...
    npm error EROFS: read-only file system

Root cause: an untrusted `ltd npx` pointed npm at a READ-ONLY harness-cache
mount and set npm_config_cache to it. npm writes _cacache/tmp even while merely
fetching package metadata, so the very first fetch dies with EROFS -- before any
tarball is downloaded. The bug fires ONLY when the host harness-cache is
"warmed" (non-empty) and the requested package is absent from it.

DETERMINISM -- why this test is reliably red on broken code:
    The bug is state-dependent. A cold cache, or a cache that already contains
    the package, both hide it. So the test OWNS the precondition: it runs `ltd`
    under an isolated $HOME whose harness-cache is warmed with a realistic but
    package-empty npm `_cacache` skeleton. That guarantees `cache_warmed` is
    true (so broken code read-only-mounts it) AND the package is absent (so npm
    must fetch and write into the read-only mount -> EROFS). The fixed code
    never mounts the cache for untrusted runs, so npm uses the cage's own
    writable cache and the fetch succeeds.

DEPLOY SKEW -- why this runs the installed `ltd`, not `uv run`:
    This test invokes the installed `ltd` CONSOLE SCRIPT -- the artifact the
    user actually runs -- NOT `uv run lamp-the-djinn` against the source tree. A
    prior regression test used `uv run` + a tiny cached package and went green
    while the shipped `ltd` stayed broken (a stale `uv tool` install running the
    old code). e2e must exercise the deployed entry point, or it cannot catch
    deploy skew. CI installs the package from the PR source before running e2e.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

# The real agent the user invoked. The bug is package-agnostic, but a faithful
# reproduction is harder to wave away.
AGENT_PACKAGE = "@earendil-works/pi-coding-agent"


def _ltd_binary() -> str | None:
    """Resolve the DEPLOYED `ltd` console script the user actually runs.

    Honors LTD_BIN for CI/local override (CI should point this at the artifact it
    installed from the PR source). Otherwise resolves `ltd` / `lamp-the-djinn`
    on PATH -- but DELIBERATELY EXCLUDING the active virtualenv's bin dir.

    Why exclude the venv: under `uv run pytest`, the project's editable install
    puts an `ltd` in `.venv/bin` that reads `src/` live -- i.e. the CURRENT
    source, fix and all. `shutil.which("ltd")` would find THAT and the e2e would
    silently validate the source instead of the deployed artifact, hiding deploy
    skew. That is precisely the false-green that shipped the EROFS bug. By
    skipping the venv shadow we resolve the real installed console script (e.g.
    `~/.local/bin/ltd`, a frozen `uv tool install`) -- the thing the user runs.

    Returns None if no non-venv entry point is installed (test skips).
    """
    override = os.environ.get("LTD_BIN")
    if override:
        return override

    venv_bin = (Path(sys.prefix) / "bin").resolve()
    search = os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p).resolve() != venv_bin
    )
    return shutil.which("ltd", path=search) or shutil.which("lamp-the-djinn", path=search)


def _warm_harness_cache(home: Path) -> None:
    """Make ``home``'s harness-cache look "warmed" with an npm cache layout.

    Broken code treats any non-empty harness-cache as warmed and read-only-mounts
    it. We mirror the real npm cache skeleton (``npm/_cacache/{tmp,content-v2,
    index-v5}``) so that, under the read-only mount, npm gets past its initial
    ``mkdir`` and fails specifically where the user failed: writing a staging
    file into ``_cacache/tmp`` (EROFS). A marker-only cache would fail earlier
    (ENOENT at ``mkdir npm``) -- same bug, but not the user's exact error path.
    """
    cacache = home / ".cache" / "lamp-the-djinn" / "harness-cache" / "npm" / "_cacache"
    for sub in ("tmp", "content-v2", "index-v5"):
        (cacache / sub).mkdir(parents=True, exist_ok=True)


def describe_spinning_up_a_coding_agent():
    """The base case: `ltd npx <coding-agent>` must launch, not crash on the cache."""

    def it_does_not_crash_with_a_readonly_cache_erofs(tmp_path: Path):
        """Bare `ltd npx -y @earendil-works/pi-coding-agent` must fetch + launch.

        The bare form (no --trusted) is what the user ran. `--help` makes the
        agent exit fast once fetched; the EROFS, if present, fires during the
        npm metadata fetch BEFORE `--help` is ever reached, so it reproduces the
        user's failure identically.
        """
        if shutil.which("docker") is None:
            pytest.skip("docker not available")
        ltd = _ltd_binary()
        if ltd is None:
            pytest.skip("ltd/lamp-the-djinn console script not installed on PATH (set LTD_BIN)")
        # Always surface WHICH artifact ran -- a wrong-binary e2e is how the bug
        # shipped green before. If this points into a .venv, the test is lying.
        print(f"\n[e2e] exercising deployed artifact: {ltd}")

        # Own the precondition: isolated HOME with a warmed-but-package-empty
        # harness-cache. This is what makes broken code deterministically EROFS.
        home = tmp_path / "home"
        home.mkdir()
        _warm_harness_cache(home)

        env = {**os.environ, "HOME": str(home)}

        result = subprocess.run(
            [ltd, "npx", "-y", AGENT_PACKAGE, "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )

        combined = f"{result.stdout}\n{result.stderr}"
        # The exact regression: a read-only harness cache the cage points npm at.
        assert "EROFS" not in combined, (
            f"`ltd npx` regressed to a read-only npm cache (EROFS) -- the exact "
            f"user-reported failure.\nrc={result.returncode}\n{combined}"
        )
        assert "read-only file system" not in combined.lower(), (
            f"`ltd npx` regressed to a read-only cache mount.\nrc={result.returncode}\n{combined}"
        )
        # Not vacuous: the agent package must actually have been fetched + run.
        assert result.returncode == 0, f"coding agent failed to spin up (rc={result.returncode}).\n{combined}"
