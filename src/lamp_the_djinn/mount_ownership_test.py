"""
Unit tests for fix_mount_dir_ownership. Docker is mocked; the assertions pin
the security-load-bearing shape of the call -- a host-side `docker exec --user
root chown`, non-recursive, on the intermediate dirs only.
"""

from unittest import mock

import pytest

from lamp_the_djinn.mount_ownership import fix_mount_dir_ownership

pytestmark = pytest.mark.unit


def describe_fix_mount_dir_ownership():
    """Re-own from the host, never via in-cage sudo."""

    def it_chowns_the_dirs_to_the_cage_user():
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="cid\n", returncode=0)) as run:
            fix_mount_dir_ownership("clanker.instance=xyz", ["/home/node/.pi", "/home/node/.pi/agent"])

        chown = run.call_args_list[-1].args[0]
        assert chown == [
            "docker",
            "exec",
            "--user",
            "root",
            "cid",
            "chown",
            "node:node",
            "/home/node/.pi",
            "/home/node/.pi/agent",
        ]
        # Non-recursive on purpose: -R would follow the bind into the host file.
        assert "-R" not in chown

    def it_does_nothing_without_dirs():
        with mock.patch("subprocess.run") as run:
            fix_mount_dir_ownership("clanker.instance=xyz", [])
        run.assert_not_called()

    def it_does_nothing_when_the_cage_is_gone():
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="", returncode=0)) as run:
            fix_mount_dir_ownership("clanker.instance=xyz", ["/home/node/.pi"])
        assert run.call_count == 1  # the lookup only

    def it_stays_quiet_on_failure_unless_debug(capsys: pytest.CaptureFixture):
        failed = mock.Mock(stdout="cid\n", returncode=1, stderr="nope")
        with mock.patch("subprocess.run", return_value=failed):
            fix_mount_dir_ownership("clanker.instance=xyz", ["/home/node/.pi"], debug=False)
        assert capsys.readouterr().err == ""

        with mock.patch("subprocess.run", return_value=failed):
            fix_mount_dir_ownership("clanker.instance=xyz", ["/home/node/.pi"], debug=True)
        assert "nope" in capsys.readouterr().err
