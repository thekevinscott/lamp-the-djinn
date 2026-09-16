"""
Integration test for the harness-cache trust gate -- the EROFS regression.

The collaborator here is the host filesystem: a *warmed* harness-cache directory
on disk. We materialize a realistic npm cache skeleton under a monkeypatched
HOME, then ask `modify_config` what devcontainer mounts/env it produces for an
UNTRUSTED run. No Docker, no container -- this is the integration tier (the
filesystem state is real and controlled, not mocked away).

Why this pairs with the e2e (tests/e2e/coding_agent_test.py): the e2e proves the
deployed `ltd` artifact no longer EROFSes; this proves, deterministically and in
milliseconds, the CONFIG decision that caused it. The bug was state-dependent --
it only fired when the host cache was warmed -- so the test OWNS that state. On
the buggy code (an `elif cache_warmed:` branch that read-only-mounted the cache
and set npm_config_cache) this goes red; on the fix (untrusted mounts nothing)
it stays green regardless of cache warmth.
"""

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.config import modify_config

pytestmark = pytest.mark.integration


def _bare_args() -> argparse.Namespace:
    """Minimal args namespace for modify_config (no extra features)."""
    return argparse.Namespace(
        build=False,
        ssh_key_file=None,
        gpg_key_id=None,
        git_user_name=None,
        git_user_email=None,
        gh_token=None,
        port=None,
        volume=None,
        env=None,
    )


def _warm_harness_cache(home: Path) -> None:
    """Materialize a realistic, non-empty npm cache so the dir reads as 'warmed'."""
    cacache = home / ".cache" / "lamp-the-djinn" / "harness-cache" / "npm" / "_cacache"
    for sub in ("tmp", "content-v2", "index-v5"):
        (cacache / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def warmed_home(tmp_path: Path) -> Iterator[Path]:
    """An isolated $HOME whose harness-cache is warmed.

    modify_config reads Path.home() to decide cache warmth, so HOME must point at
    the warmed dir. patch.dict (not monkeypatch / in-place mutation) keeps the env
    change scoped and restores it on teardown -- the mock-mechanism hygiene the
    integration-lint rule enforces.
    """
    home = tmp_path / "home"
    home.mkdir()
    _warm_harness_cache(home)
    with mock.patch.dict("os.environ", {"HOME": str(home)}):
        yield home


def describe_untrusted_run_with_a_warmed_host_cache():
    """The exact precondition that produced EROFS: untrusted + a warmed host cache."""

    def it_neither_mounts_the_cache_nor_points_npm_at_it(tmp_path: Path, warmed_home: Path):
        """Untrusted must add NO harness-cache mount and NO cache env, even warmed.

        A read-only harness-cache mount + npm_config_cache pointing at it is the
        bug: npm writes _cacache/tmp even while fetching, so the read-only mount
        fails with EROFS. The cage must fall back to its own writable cache.
        """
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            trusted=False,
        )

        run_args = config.get("runArgs", [])
        mounts = config.get("mounts", [])
        assert not any("ltd-harness" in m for m in mounts), (
            f"untrusted run must not mount the harness cache (warmed or not): {mounts}"
        )
        assert not any(a.startswith("npm_config_cache=") for a in run_args), (
            f"untrusted run must not point npm at the harness cache: {run_args}"
        )
        assert not any(a.startswith("UV_CACHE_DIR=") for a in run_args), (
            f"untrusted run must not point uv at the harness cache: {run_args}"
        )
        assert not any("ltd-harness" in a for a in run_args), (
            f"untrusted run must set no harness cache env at all: {run_args}"
        )
