"""Unit tests for check_docker_accessible: the fail-fast Docker preflight."""

from unittest import mock

import pytest

from lamp_the_djinn.docker_check import check_docker_accessible

pytestmark = pytest.mark.unit


def describe_check_docker_accessible():
    """A reachable daemon is silent; an unreachable one exits 1 with guidance."""

    def it_returns_quietly_when_docker_answers(capsys: pytest.CaptureFixture):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            check_docker_accessible()
        run.assert_called_once_with(["docker", "info"], capture_output=True, text=True)
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("returncode", [1, -9])
    def it_exits_one_when_docker_is_unreachable(capsys: pytest.CaptureFixture, returncode: int):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=returncode)):
            with pytest.raises(SystemExit) as exc:
                check_docker_accessible()
        assert exc.value.code == 1
        assert "Docker is not running" in capsys.readouterr().err

    def it_exits_one_when_docker_is_not_installed(capsys: pytest.CaptureFixture):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("docker")):
            with pytest.raises(SystemExit) as exc:
                check_docker_accessible()
        assert exc.value.code == 1
        assert "Docker is not installed" in capsys.readouterr().err
