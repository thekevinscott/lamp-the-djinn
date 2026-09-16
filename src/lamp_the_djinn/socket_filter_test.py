"""Unit tests for the copytree socket filter."""

from unittest import mock

import pytest

from lamp_the_djinn.socket_filter import ignore_sockets

pytestmark = pytest.mark.unit

S_IFSOCK = 0o140000
S_IFREG = 0o100000


def _lstat_returning(mode: int):
    return mock.Mock(return_value=mock.Mock(st_mode=mode))


def describe_ignoring_sockets():
    def it_drops_a_socket():
        with mock.patch("lamp_the_djinn.socket_filter.os.lstat", _lstat_returning(S_IFSOCK | 0o600)):
            assert ignore_sockets("/gnupg", ["S.gpg-agent"]) == {"S.gpg-agent"}

    def it_keeps_ordinary_files():
        with mock.patch("lamp_the_djinn.socket_filter.os.lstat", _lstat_returning(S_IFREG | 0o600)):
            assert ignore_sockets("/gnupg", ["pubring.kbx"]) == set()

    def it_drops_entries_it_cannot_stat():
        """A name that vanished between listdir and lstat is skipped, not raised on."""
        with mock.patch("lamp_the_djinn.socket_filter.os.lstat", side_effect=FileNotFoundError):
            assert ignore_sockets("/gnupg", ["gone"]) == {"gone"}
