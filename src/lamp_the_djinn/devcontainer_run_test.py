"""
Unit tests for run_devcontainer. Every collaborator is mocked -- no container
is created; the e2e tier exercises the real lifecycle. What is pinned here is
the wiring: the `up`/`exec` argv, the post-`up` re-own, unconditional teardown,
and the shell-style exit code.
"""

from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.devcontainer_run import run_devcontainer

pytestmark = pytest.mark.unit


def _popen(returncode: int = 0) -> mock.Mock:
    child = mock.Mock()
    child.returncode = returncode
    child.communicate.return_value = ("", "")
    child.poll.return_value = returncode
    return child


def _run(popen: mock.Mock, **kwargs):
    """Drive run_devcontainer with subprocess + both docker helpers mocked."""
    with (
        mock.patch("lamp_the_djinn.devcontainer_run.subprocess.Popen", popen),
        mock.patch("lamp_the_djinn.devcontainer_run.teardown_cage") as teardown,
        mock.patch("lamp_the_djinn.devcontainer_run.fix_mount_dir_ownership") as fix_owner,
        mock.patch("lamp_the_djinn.devcontainer_run.discard_staged_dirs") as discard,
    ):
        with pytest.raises(SystemExit) as exc:
            run_devcontainer(
                Path("/cfg/devcontainer.json"),
                Path("/ws"),
                Path("/proj"),
                instance_id="xyz",
                debug=True,
                **kwargs,
            )
    return exc.value, teardown, fix_owner, discard


def describe_run_devcontainer():
    """Bring the cage up, run the command, always tear down."""

    def it_labels_up_and_exec_with_the_instance_id():
        popen = mock.Mock(side_effect=[_popen(0), _popen(0)])
        _run(popen, command=["claude", "-p", "hi"])

        up_cmd = popen.call_args_list[0].args[0]
        exec_cmd = popen.call_args_list[1].args[0]
        assert up_cmd[:4] == ["npx", "-y", "@devcontainers/cli", "up"]
        assert "clanker.instance=xyz" in up_cmd
        assert exec_cmd[3] == "exec"
        assert "clanker.instance=xyz" in exec_cmd
        # The resolved command is appended verbatim after the devcontainer flags.
        assert exec_cmd[-3:] == ["claude", "-p", "hi"]

    def it_defaults_the_command_when_none_is_given():
        popen = mock.Mock(side_effect=[_popen(0), _popen(0)])
        _run(popen)

        exec_cmd = popen.call_args_list[1].args[0]
        assert exec_cmd[-2:] == ["claude", "--dangerously-skip-permissions"]

    def it_reowns_mount_parents_after_the_cage_is_up():
        popen = mock.Mock(side_effect=[_popen(0), _popen(0)])
        _, _, fix_owner, _ = _run(popen, mount_parent_dirs=["/home/node/.pi"])

        fix_owner.assert_called_once_with("clanker.instance=xyz", ["/home/node/.pi"], True)

    def it_propagates_the_child_exit_code():
        popen = mock.Mock(side_effect=[_popen(0), _popen(3)])
        exit_exc, _, _, _ = _run(popen)
        assert exit_exc.code == 3

    def it_maps_a_killed_child_to_the_shell_convention():
        """A child killed by signal N reports -N; a shell reports 128 + N."""
        popen = mock.Mock(side_effect=[_popen(0), _popen(-9)])
        exit_exc, _, _, _ = _run(popen)
        assert exit_exc.code == 137

    def it_tears_the_cage_down_even_when_up_fails():
        """`up` returning non-zero must not leak a half-created cage."""
        popen = mock.Mock(side_effect=[_popen(1)])
        with (
            mock.patch("lamp_the_djinn.devcontainer_run.subprocess.Popen", popen),
            mock.patch("lamp_the_djinn.devcontainer_run.teardown_cage") as teardown,
            mock.patch("lamp_the_djinn.devcontainer_run.fix_mount_dir_ownership"),
        ):
            with pytest.raises(Exception):  # noqa: B017 - CalledProcessError propagates
                run_devcontainer(
                    Path("/cfg/devcontainer.json"),
                    Path("/ws"),
                    Path("/proj"),
                    instance_id="xyz",
                    debug=True,
                )
        teardown.assert_called_once_with("clanker.instance=xyz")

    def it_tears_the_cage_down_on_success():
        popen = mock.Mock(side_effect=[_popen(0), _popen(0)])
        _, teardown, _, _ = _run(popen)
        teardown.assert_called_once_with("clanker.instance=xyz")

    def it_discards_the_staged_dirs_once_the_cage_is_down():
        """The staged keyring holds private key material; it must not outlive the run."""
        popen = mock.Mock(side_effect=[_popen(0), _popen(0)])
        _, _, _, discard = _run(popen, discard_dirs=[Path("/cache/gnupg-stage")])

        discard.assert_called_once_with([Path("/cache/gnupg-stage")])
