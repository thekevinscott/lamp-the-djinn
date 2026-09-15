"""Unit tests for teardown_cage. Docker is mocked; no container is touched."""

from unittest import mock

import pytest

from lamp_the_djinn.teardown import teardown_cage

pytestmark = pytest.mark.unit


def describe_teardown_cage():
    """Resolve the labelled container ids, then force-remove them."""

    def it_removes_every_labelled_container():
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="abc def\n")) as run:
            teardown_cage("clanker.instance=xyz")

        rm = run.call_args_list[-1].args[0]
        assert rm[:3] == ["docker", "rm", "-f"]
        assert rm[3:] == ["abc", "def"]

    def it_filters_by_the_instance_label():
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="")) as run:
            teardown_cage("clanker.instance=xyz")

        ps = run.call_args_list[0].args[0]
        assert "label=clanker.instance=xyz" in ps

    def it_does_nothing_when_no_container_matches():
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="  \n")) as run:
            teardown_cage("clanker.instance=xyz")

        assert run.call_count == 1  # the lookup only; no `docker rm`
