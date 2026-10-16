"""
Integration test for what a run leaves on the host -- issues #124, #125, #132.

`main` runs for real against an isolated HOME. The only fake is the external
boundary: `docker` and `npx` (the devcontainer CLI) are stub scripts on PATH, so
no container is created and nothing first-party is mocked.

Each run's workspace dir under ~/.cache holds secrets: the staged ~/.gnupg copy
(private keys) and devcontainer.json, whose postStartCommand carries the
--gh-token. Whatever happens, that dir must be gone when ltd returns, and a
failed `devcontainer up` must end in a one-line error, not a traceback.
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.cli import main

pytestmark = pytest.mark.integration

TOKEN = "ghp_integration_secret_token"

# `devcontainer up` exits FAKE_UP_RC; everything else succeeds silently.
_FAKE_NPX = """#!/bin/sh
case " $* " in
  *" up "*) echo "fake up failed" >&2; exit "${FAKE_UP_RC:-0}" ;;
esac
exit 0
"""


@pytest.fixture
def host(tmp_path: Path) -> Iterator[Path]:
    """An isolated HOME with stub docker/npx on PATH, cwd'd into a project dir."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "npx").write_text(_FAKE_NPX)
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    project = tmp_path / "proj"
    project.mkdir()

    env = {k: v for k, v in os.environ.items() if k not in ("LTD_GH_TOKEN", "FAKE_UP_RC")}
    env.update(HOME=str(home), PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    with (
        mock.patch.dict("os.environ", env, clear=True),
        mock.patch("pathlib.Path.cwd", return_value=project),
        mock.patch("sys.argv", ["ltd"]),
    ):
        yield home


@pytest.fixture
def failing_up(host: Path) -> Iterator[Path]:
    with mock.patch.dict("os.environ", {"FAKE_UP_RC": "7"}):
        yield host


def _main(*argv: str) -> None:
    sys.argv[1:] = argv  # the `host` fixture owns sys.argv and restores it
    main()


def _run(*argv: str) -> SystemExit:
    with pytest.raises(SystemExit) as exc:
        _main(*argv)
    return exc.value


def _workspaces(home: Path) -> list[Path]:
    return list((home / ".cache" / "lamp-the-djinn").glob("workspace-*"))


def describe_a_run_leaves_no_secrets_on_the_host():
    def it_removes_the_workspace_holding_the_gh_token(host: Path):
        """#124: devcontainer.json carries the token; the dir must not outlive the run."""
        exit_exc = _run("--gh-token", TOKEN, "true")

        assert exit_exc.code == 0
        assert _workspaces(host) == []

    def it_removes_the_staged_keyring_when_setup_fails(host: Path):
        """#125: a failure after staging begins must not strand the private-key copy.

        A FIFO in ~/.gnupg makes the copy fail after the private key has landed.
        """
        gnupg = host / ".gnupg" / "private-keys-v1.d"
        gnupg.mkdir(parents=True)
        (gnupg / "ABCDEF.key").write_bytes(b"secret")
        os.mkfifo(host / ".gnupg" / "zz-fifo")

        with pytest.raises(Exception):  # noqa: B017 - the staging error itself still surfaces
            _main("--gpg-key-id", "C567F8478F289CC4", "true")

        assert list(host.rglob("ABCDEF.key")) == [host / ".gnupg" / "private-keys-v1.d" / "ABCDEF.key"]
        assert _workspaces(host) == []


def describe_a_failed_devcontainer_up():
    def it_exits_nonzero_with_a_one_line_error(failing_up: Path, capsys: pytest.CaptureFixture[str]):
        """#132: no CalledProcessError traceback escapes main."""
        exit_exc = _run("--gh-token", TOKEN, "true")

        assert exit_exc.code == 7
        assert "Error: devcontainer up failed (exit 7)" in capsys.readouterr().err
        assert _workspaces(failing_up) == []
