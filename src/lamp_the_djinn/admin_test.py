"""Unit tests for the admin subcommand reservation and its terminal lifecycle."""

import io

import pytest

from .admin import is_admin_command, run_admin
from .admin_screen import TITLE

pytestmark = pytest.mark.unit


class FakeStream(io.StringIO):
    """A StringIO that can claim to be (or not be) a terminal."""

    def __init__(self, tty: bool = False):
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def describe_reserving_the_admin_subcommand():
    def it_claims_the_bare_admin_token():
        assert is_admin_command(["admin"]) is True

    @pytest.mark.parametrize(
        "command",
        [
            pytest.param(["admin", "--status"], id="admin-with-a-flag"),
            pytest.param(["admin", "serve"], id="admin-with-an-argument"),
            pytest.param(["sudo", "admin"], id="admin-as-a-later-token"),
            pytest.param(["administer"], id="a-longer-name-that-starts-with-admin"),
            pytest.param([], id="no-command-at-all"),
        ],
    )
    def it_leaves_every_other_form_to_the_cage(command):
        assert is_admin_command(command) is False


def describe_running_the_admin_screen_without_a_terminal():
    def it_prints_the_frame_once_and_exits():
        stdout = FakeStream(tty=False)

        code = run_admin(stdin=FakeStream(tty=False), stdout=stdout)

        assert code == 0
        assert TITLE in stdout.getvalue()

    def it_takes_over_no_terminal_when_only_stdin_is_a_tty():
        """Redirected stdout must not get alternate-screen escapes."""
        stdout = FakeStream(tty=False)

        run_admin(stdin=FakeStream(tty=True), stdout=stdout)

        assert "\x1b[?1049h" not in stdout.getvalue()
