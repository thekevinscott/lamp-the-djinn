"""
Unit tests for main(), the composition root. Every collaborator is mocked, so
what is pinned here is the wiring main owns: proxy engagement, the SSH-key
preflight, and the build fallback when the published image cannot be pulled.
The behavior of each collaborator is pinned in its own colocated suite.

Style is pytest-describe (describe_/it_ blocks).
"""

from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.cli import main

pytestmark = pytest.mark.unit

# The exact exception main catches around the image pull, reached through the unit
# under test so this file imports no effectful collaborator of its own.
_CalledProcessError = main.__globals__["subprocess"].CalledProcessError


def _wire(tmp_path: Path, argv: list[str]):
    """Patch every collaborator main calls, and run it under `argv`.

    Returns the mock registry so a cell can assert on the wiring. The devcontainer
    source config is a real file under tmp_path because main reads and rewrites it.
    """
    cache_dir = tmp_path / "cache"
    (cache_dir / ".devcontainer").mkdir(parents=True)
    (cache_dir / ".devcontainer" / "devcontainer.json").write_text("{}")

    patches = {
        "extract_devcontainer_files": mock.DEFAULT,
        "check_docker_accessible": mock.DEFAULT,
        "detect_runtime": mock.DEFAULT,
        "pull_docker_image_if_needed": mock.DEFAULT,
        "print_container_info": mock.DEFAULT,
        "stage_claude_config": mock.DEFAULT,
        "run_admin": mock.DEFAULT,
        "modify_config": mock.DEFAULT,
        "home_mount_parent_dirs": mock.DEFAULT,
        "run_devcontainer": mock.DEFAULT,
        "record_manifest": mock.DEFAULT,
    }
    with mock.patch.multiple("lamp_the_djinn.cli", **patches) as mocks:
        mocks["extract_devcontainer_files"].return_value = cache_dir
        mocks["detect_runtime"].return_value = "runc"
        mocks["modify_config"].return_value = {}
        mocks["home_mount_parent_dirs"].return_value = []
        with (
            mock.patch("sys.argv", ["ltd", *argv]),
            mock.patch("pathlib.Path.home", return_value=tmp_path / "home"),
            mock.patch("pathlib.Path.cwd", return_value=tmp_path / "proj"),
        ):
            main()
    return mocks


def describe_proxy_engagement():
    """Provider env is injected only on explicit opt-in, never by giving a command."""

    def it_defaults_the_proxy_url_when_the_model_flag_engages_it(tmp_path: Path):
        mocks = _wire(tmp_path, ["--model", "glm-5.2"])
        assert mocks["modify_config"].call_args.kwargs["proxy_url"] == "http://host.docker.internal:4000/v1"

    def it_leaves_the_proxy_unset_for_a_bare_command(tmp_path: Path):
        """`ltd npx pi ...` must NOT engage the proxy: the harness uses its own config."""
        mocks = _wire(tmp_path, ["npx", "pi"])
        assert mocks["modify_config"].call_args.kwargs["proxy_url"] is None

    def it_honors_an_explicit_proxy_url(tmp_path: Path):
        mocks = _wire(tmp_path, ["--proxy-url", "http://elsewhere:9/v1"])
        assert mocks["modify_config"].call_args.kwargs["proxy_url"] == "http://elsewhere:9/v1"


def describe_ssh_key_preflight():
    """A --ssh-key-file that does not exist fails before Docker is touched."""

    def it_exits_one_for_a_missing_key(tmp_path: Path):
        with pytest.raises(SystemExit) as exc:
            _wire(tmp_path, ["--ssh-key-file", str(tmp_path / "absent")])
        assert exc.value.code == 1


def describe_image_fallback():
    """A pull failure falls back to a local build instead of crashing the run."""

    def it_switches_to_build_when_the_pull_fails(tmp_path: Path):
        cache_dir = tmp_path / "cache"
        (cache_dir / ".devcontainer").mkdir(parents=True)
        (cache_dir / ".devcontainer" / "devcontainer.json").write_text("{}")

        with mock.patch.multiple(
            "lamp_the_djinn.cli",
            extract_devcontainer_files=mock.DEFAULT,
            check_docker_accessible=mock.DEFAULT,
            detect_runtime=mock.DEFAULT,
            pull_docker_image_if_needed=mock.DEFAULT,
            stage_claude_config=mock.DEFAULT,
            modify_config=mock.DEFAULT,
            home_mount_parent_dirs=mock.DEFAULT,
            run_devcontainer=mock.DEFAULT,
            record_manifest=mock.DEFAULT,
        ) as mocks:
            mocks["extract_devcontainer_files"].return_value = cache_dir
            mocks["detect_runtime"].return_value = "runc"
            mocks["modify_config"].return_value = {}
            mocks["home_mount_parent_dirs"].return_value = []
            mocks["pull_docker_image_if_needed"].side_effect = _CalledProcessError(1, "docker pull")
            with (
                mock.patch("sys.argv", ["ltd"]),
                mock.patch("pathlib.Path.home", return_value=tmp_path / "home"),
                mock.patch("pathlib.Path.cwd", return_value=tmp_path / "proj"),
            ):
                main()

            args = mocks["modify_config"].call_args.args[1]
            assert args.build is True


def describe_cage_wiring():
    """main hands the resolved pieces to the collaborators that use them."""

    def it_stages_a_claude_copy_by_default(tmp_path: Path):
        mocks = _wire(tmp_path, [])
        mocks["stage_claude_config"].assert_called_once()
        assert mocks["modify_config"].call_args.kwargs["claude_stage_dir"] is not None

    def it_skips_staging_when_trusted(tmp_path: Path):
        mocks = _wire(tmp_path, ["--trusted"])
        mocks["stage_claude_config"].assert_not_called()
        assert mocks["modify_config"].call_args.kwargs["claude_stage_dir"] is None

    def it_records_the_command_to_the_manifest(tmp_path: Path):
        mocks = _wire(tmp_path, ["npx", "-y", "aider"])
        mocks["record_manifest"].assert_called_once_with(["npx", "-y", "aider"])

    def it_hands_the_resolved_runtime_to_modify_config(tmp_path: Path):
        mocks = _wire(tmp_path, [])
        assert mocks["modify_config"].call_args.kwargs["runtime"] == "runc"


def describe_the_admin_subcommand():
    """`ltd admin` is host-side: it must never reach the cage or probe Docker."""

    def it_dispatches_before_any_cage_setup(tmp_path: Path):
        cache_dir = tmp_path / "cache"
        (cache_dir / ".devcontainer").mkdir(parents=True)
        (cache_dir / ".devcontainer" / "devcontainer.json").write_text("{}")

        with mock.patch.multiple(
            "lamp_the_djinn.cli",
            check_docker_accessible=mock.DEFAULT,
            run_devcontainer=mock.DEFAULT,
            run_admin=mock.DEFAULT,
        ) as mocks:
            mocks["run_admin"].return_value = 0
            with mock.patch("sys.argv", ["ltd", "admin"]), pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 0
        mocks["run_admin"].assert_called_once()
        mocks["check_docker_accessible"].assert_not_called()
        mocks["run_devcontainer"].assert_not_called()

    def it_leaves_a_cage_command_named_admin_alone(tmp_path: Path):
        mocks = _wire(tmp_path, ["admin", "--status"])
        mocks["run_admin"].assert_not_called()
        mocks["run_devcontainer"].assert_called_once()
