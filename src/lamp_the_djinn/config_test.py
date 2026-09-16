"""
Unit tests for modify_config: provider env injection, the trust-gated harness
cache, path-identity mounts, trust-tiered ~/.claude exposure, the per-cage
memory default, and the firewall allowlist supplement mounts.

Style is pytest-describe (describe_/it_ blocks) with unittest.mock + tmp_path
rather than the pytest-mock `mocker` fixture, which is not in the dev
dependency set.
"""

import argparse
from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.config import modify_config

pytestmark = pytest.mark.unit


def _bare_args(**overrides) -> argparse.Namespace:
    """A minimal args namespace for modify_config (strict, no extra features).

    `trusted`/`memory` carry their CLI defaults so a call with no overrides is
    the bare untrusted invocation; pass overrides (e.g. `trusted=True`) per test.
    """
    base = dict(
        build=False,
        ssh_key_file=None,
        gpg_key_id=None,
        git_user_name=None,
        git_user_email=None,
        gh_token=None,
        port=None,
        volume=None,
        env=None,
        allow_domains_file=None,
        trusted=False,
        memory=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _mounts(config: dict) -> list[str]:
    return config.get("mounts", [])


def _run_args(config: dict) -> list[str]:
    return config.get("runArgs", [])


def describe_dual_env_injection():
    """modify_config injects both env families iff the proxy is engaged."""

    def it_injects_both_families_when_proxy_engaged(tmp_path: Path):
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            proxy_url="http://host.docker.internal:4000/v1",
            model="glm-5.2",
            proxy_api_key="k",
        )
        run_args = _run_args(config)
        joined = " ".join(run_args)
        assert "OPENAI_BASE_URL=http://host.docker.internal:4000/v1" in run_args
        assert "OPENAI_MODEL=glm-5.2" in run_args
        assert "ANTHROPIC_BASE_URL=http://host.docker.internal:4000/v1" in run_args
        assert "ANTHROPIC_MODEL=glm-5.2" in run_args
        # host.docker.internal mapping is added so the cage can reach the proxy.
        assert "--add-host=host.docker.internal:host-gateway" in run_args
        assert "host" in joined

    def it_injects_no_provider_env_when_no_proxy(tmp_path: Path):
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            proxy_url=None,
        )
        run_args = _run_args(config)
        assert not any(a.startswith("OPENAI_") or "OPENAI_" in a for a in run_args)
        assert not any(a.startswith("ANTHROPIC_") or "ANTHROPIC_" in a for a in run_args)

    def it_always_adds_host_gateway_even_without_proxy(tmp_path: Path):
        """The host.docker.internal mapping is unconditional: a harness config (e.g.
        pi's models.json) may point at it even when ltd injects no provider env."""
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            proxy_url=None,
        )
        assert "--add-host=host.docker.internal:host-gateway" in _run_args(config)

    def it_adds_writable_auth_mount_always(tmp_path: Path):
        """The scoped, writable credential mount is present regardless of proxy."""
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            proxy_url=None,
        )
        mounts = " ".join(config["mounts"])
        assert "/home/node/.config/ltd-auth" in mounts
        # NOT readonly -- this mount must be writable to persist credentials.
        auth_mount = next(m for m in config["mounts"] if "ltd-auth" in m)
        assert "readonly" not in auth_mount


def _warm_harness_cache(home: Path) -> None:
    """Materialize a realistic, non-empty npm cache so the dir reads as 'warmed'.

    The EROFS bug was state-dependent: the buggy `elif cache_warmed:` branch only
    read-only-mounted the cache when the host harness-cache was non-empty. Warming
    a monkeypatched HOME makes the untrusted assertions reproduce that precondition
    deterministically, instead of depending on whatever the developer's real
    ~/.cache happens to contain.
    """
    cacache = home / ".cache" / "lamp-the-djinn" / "harness-cache" / "npm" / "_cacache"
    for sub in ("tmp", "content-v2", "index-v5"):
        (cacache / sub).mkdir(parents=True, exist_ok=True)


def describe_harness_cache():
    """The harness package cache mount is trust-gated, not proxy-gated."""

    def it_mounts_writable_cache_and_env_when_trusted(tmp_path: Path):
        """trusted -> writable cache bind + cache env, so npx/uvx reuse the cache."""
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            trusted=True,
        )
        run_args = _run_args(config)
        assert "UV_CACHE_DIR=/home/node/.cache/ltd-harness/uv" in run_args
        assert "npm_config_cache=/home/node/.cache/ltd-harness/npm" in run_args
        # The harness-cache mount is present and writable (NOT readonly).
        cache_mount = next(m for m in config["mounts"] if "ltd-harness" in m)
        assert "harness-cache" in cache_mount
        assert "readonly" not in cache_mount

    def it_does_not_mount_cache_or_set_env_when_untrusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Regression for the EROFS crash on bare `ltd npx` (no --trusted).

        Untrusted runs must NOT mount the harness cache AND must NOT point
        npm/uv at it. If npm_config_cache/UV_CACHE_DIR point at a read-only
        mount, npm writes _cacache/tmp while fetching and dies with EROFS.
        The cage must fall back to its own writable in-container cache.

        The cache is WARMED under a monkeypatched HOME so the assertion holds in
        the exact state that triggered the bug -- not just when the developer's
        ambient ~/.cache happens to be empty.
        """
        home = tmp_path / "home"
        home.mkdir()
        _warm_harness_cache(home)
        monkeypatch.setenv("HOME", str(home))

        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            trusted=False,
        )
        run_args = _run_args(config)
        # No cache env pointing at the harness mount.
        assert not any("ltd-harness" in a for a in run_args), (
            f"untrusted run must not set a harness cache env: {run_args}"
        )
        assert not any(a.startswith("npm_config_cache=") for a in run_args)
        assert not any(a.startswith("UV_CACHE_DIR=") for a in run_args)
        # No harness-cache bind mount at all.
        assert not any("ltd-harness" in m for m in config.get("mounts", [])), (
            f"untrusted run must not mount the harness cache: {config.get('mounts')}"
        )


def describe_path_identity_mounts():
    """Host dirs mount at their own paths inside the cage (path identity)."""

    def it_mounts_the_project_at_its_own_path(tmp_path: Path):
        proj = tmp_path / "proj"
        proj.mkdir()
        config = modify_config(
            {"mounts": [], "runArgs": []},
            _bare_args(),
            tmp_path,
            project_dir=proj,
        )
        # target == source == the real host path, not /workspace.
        assert config["workspaceMount"] == (f"source={proj},target={proj},type=bind,consistency=delegated")
        assert config["workspaceFolder"] == str(proj)
        assert "/workspace" not in config["workspaceMount"]

    def it_identity_mounts_a_bare_volume_path(tmp_path: Path):
        d = tmp_path / "bertha" / "app"
        d.mkdir(parents=True)
        args = _bare_args()
        args.volume = [str(d)]
        config = modify_config({"mounts": [], "runArgs": []}, args, tmp_path)
        resolved = str(Path(str(d)).resolve())
        assert f"{resolved}:{resolved}" in config["runArgs"]

    def it_remaps_a_home_relative_volume_to_the_cage_home(tmp_path: Path, monkeypatch):
        """A `-v` path UNDER the host HOME maps to the SAME relative spot under the
        cage user's HOME (`~/.pi` -> `/home/node/.pi`). The cage runs as `node`, so
        a path-identity mount of a `$HOME` path would land where the harness (pi)
        never looks. Monkeypatch HOME so the test owns the precondition."""
        home = tmp_path / "home" / "duncan"
        home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        args = _bare_args()
        args.volume = [str(home / ".pi")]
        config = modify_config({"mounts": [], "runArgs": []}, args, tmp_path)
        src = str((home / ".pi").resolve())
        assert f"{src}:/home/node/.pi" in config["runArgs"]

    def it_preserves_an_explicit_host_colon_container_volume(tmp_path: Path):
        args = _bare_args()
        args.volume = ["/h/data:/container/data"]
        config = modify_config({"mounts": [], "runArgs": []}, args, tmp_path)
        assert "/h/data:/container/data" in config["runArgs"]

    def it_mounts_multiple_volumes(tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        args = _bare_args()
        args.volume = [str(a), str(b)]
        config = modify_config({"mounts": [], "runArgs": []}, args, tmp_path)
        for d in (a, b):
            r = str(Path(str(d)).resolve())
            assert f"{r}:{r}" in config["runArgs"]


def describe_strict_claude_mount():
    """Default (strict): mount the staged COPY, write back only transcript data."""

    def it_mounts_the_stage_dir_not_the_host_claude(tmp_path: Path):
        stage = tmp_path / "stage"
        stage.mkdir()
        # An embedded-style live rw host .claude bind that must be filtered out.
        config = {
            "mounts": ["source=${localEnv:HOME}/.claude,target=/home/node/.claude,type=bind"],
            "runArgs": [],
        }
        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(config, _bare_args(), tmp_path, trusted=False, claude_stage_dir=stage)

        mounts = _mounts(config)
        # The .claude root mount source is the stage dir, NOT the host config.
        assert f"source={stage},target=/home/node/.claude,type=bind" in mounts
        # No LIVE rw bind of the host ~/.claude root.
        assert "source=${localEnv:HOME}/.claude,target=/home/node/.claude,type=bind" not in mounts

    def it_writes_back_transcript_data_when_host_paths_exist(tmp_path: Path):
        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        (home / ".claude" / "history.jsonl").write_text("{}\n")
        stage = tmp_path / "stage"
        stage.mkdir()

        with mock.patch("pathlib.Path.home", return_value=home):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=stage,
            )

        mounts = _mounts(config)
        assert "source=${localEnv:HOME}/.claude/projects,target=/home/node/.claude/projects,type=bind" in mounts
        assert (
            "source=${localEnv:HOME}/.claude/history.jsonl,target=/home/node/.claude/history.jsonl,type=bind" in mounts
        )

    def it_omits_transcript_mounts_when_host_paths_absent(tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        stage = tmp_path / "stage"
        stage.mkdir()

        with mock.patch("pathlib.Path.home", return_value=home):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=stage,
            )

        mounts = " ".join(_mounts(config))
        assert "/home/node/.claude/projects" not in mounts
        assert "/home/node/.claude/history.jsonl" not in mounts


def describe_trusted_claude_mount():
    """Opt-in trusted: live read-write bind of the host ~/.claude."""

    def it_mounts_the_live_host_claude_rw(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(trusted=True),
                tmp_path,
                trusted=True,
                claude_stage_dir=None,
            )

        mounts = _mounts(config)
        assert "source=${localEnv:HOME}/.claude,target=/home/node/.claude,type=bind" in mounts
        # No readonly qualifier -- trusted is read-write.
        claude_mount = next(m for m in mounts if "/home/node/.claude,type=bind" in m)
        assert "readonly" not in claude_mount


def describe_memory_density():
    """Per-cage memory cap: 2g default, --memory override, no duplicates."""

    def it_defaults_to_2g(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(
                {"mounts": [], "runArgs": ["--memory=8g", "--cpus=4", "--pids-limit=500"]},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        run_args = _run_args(config)
        assert "--memory=2g" in run_args
        # The old 8g cap is gone; exactly one --memory remains.
        assert "--memory=8g" not in run_args
        assert sum(1 for a in run_args if a.startswith("--memory")) == 1
        # --cpus / --pids-limit untouched.
        assert "--cpus=4" in run_args
        assert "--pids-limit=500" in run_args

    def it_honors_the_memory_override(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(
                {"mounts": [], "runArgs": ["--memory=8g"]},
                _bare_args(memory="4g"),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        run_args = _run_args(config)
        assert "--memory=4g" in run_args
        assert sum(1 for a in run_args if a.startswith("--memory")) == 1

    def it_strips_separate_token_memory_pair(tmp_path: Path):
        """A `--memory VALUE` pair (two tokens) is removed, not just --memory=VALUE."""
        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(
                {"mounts": [], "runArgs": ["--memory", "8g", "--cpus=4"]},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        run_args = _run_args(config)
        assert "8g" not in run_args
        assert "--memory" not in run_args  # bare token form gone
        assert "--memory=2g" in run_args
        assert "--cpus=4" in run_args


def describe_allowlist_supplement_mount():
    """Machine-local domains file is bind-mounted read-only when present."""

    def it_mounts_the_supplement_file_when_present(tmp_path: Path):
        home = tmp_path / "home"
        cfg = home / ".config" / "lamp-the-djinn"
        cfg.mkdir(parents=True)
        domains = cfg / "allowed-domains.txt"
        domains.write_text("example.internal\n")

        with mock.patch("pathlib.Path.home", return_value=home):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        mount = next(m for m in _mounts(config) if "ltd-allowed-domains.txt" in m)
        assert f"source={domains}" in mount
        assert "target=/usr/local/share/ltd-allowed-domains.txt" in mount
        assert "readonly" in mount

    def it_omits_the_supplement_mount_when_absent(tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()

        with mock.patch("pathlib.Path.home", return_value=home):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        assert not any("ltd-allowed-domains.txt" in m for m in _mounts(config))


def describe_allow_domains_file_mount():
    """--allow-domains-file mounts a per-run domains file read-only into the cage."""

    def it_mounts_the_run_file_when_flag_set(tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        run_file = tmp_path / "this-task-domains.txt"
        run_file.write_text("example.internal\n")

        with mock.patch("pathlib.Path.home", return_value=home):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(allow_domains_file=str(run_file)),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        mount = next(m for m in _mounts(config) if "ltd-allowed-domains.run.txt" in m)
        assert f"source={run_file}" in mount
        assert "target=/usr/local/share/ltd-allowed-domains.run.txt" in mount
        assert "readonly" in mount

    def it_omits_the_run_mount_when_flag_absent(tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()

        with mock.patch("pathlib.Path.home", return_value=home):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(),
                tmp_path,
                trusted=False,
                claude_stage_dir=tmp_path / "stage",
            )

        assert not any("ltd-allowed-domains.run.txt" in m for m in _mounts(config))


def describe_gpg_keyring_staging():
    """--gpg-key-id mounts a disposable, WRITABLE copy of the host keyring.

    gpg-agent writes its socket and lockfiles inside GNUPGHOME, so the old
    read-only bind of the host ~/.gnupg broke signing outright.
    """

    def it_mounts_the_stage_dir_writable(tmp_path: Path):
        stage = tmp_path / "gnupg-stage"
        stage.mkdir()

        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(
                {"mounts": [], "runArgs": []},
                _bare_args(gpg_key_id="C567F8478F289CC4"),
                tmp_path,
                gnupg_stage_dir=stage,
            )

        gnupg_mounts = [m for m in _mounts(config) if "/home/node/.gnupg" in m]
        assert gnupg_mounts == [f"source={stage},target=/home/node/.gnupg,type=bind"]

    def it_drops_any_host_keyring_bind(tmp_path: Path):
        stage = tmp_path / "gnupg-stage"
        stage.mkdir()
        config = {"mounts": ["source=${localEnv:HOME}/.gnupg,target=/home/node/.gnupg,type=bind"], "runArgs": []}

        with mock.patch("pathlib.Path.home", return_value=tmp_path / "home"):
            config = modify_config(
                config,
                _bare_args(gpg_key_id="C567F8478F289CC4"),
                tmp_path,
                gnupg_stage_dir=stage,
            )

        assert not any("localEnv:HOME}/.gnupg" in m for m in _mounts(config))
