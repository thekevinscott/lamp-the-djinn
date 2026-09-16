"""
Unit tests for the isolation seam (runtime selection).

These tests verify detect_runtime() resolves the requested OCI runtime against
what Docker reports, falling back to runc safely. They mock subprocess.run so no
real Docker daemon is needed.

Style mirrors tests/test_cli.py (pytest-describe describe_/it_ blocks). The
existing suite mocks via unittest.mock rather than the pytest-mock `mocker`
fixture, which is not in the dev dependency set; we follow that pattern here.
"""

import json
from collections.abc import Iterator
from unittest import mock

import pytest

from lamp_the_djinn.runtime import detect_runtime

pytestmark = pytest.mark.integration


def _docker_info_result(runtimes: dict, returncode: int = 0) -> mock.Mock:
    """Build a fake `docker info --format '{{json .Runtimes}}'` result."""
    result = mock.Mock()
    result.returncode = returncode
    result.stdout = json.dumps(runtimes)
    return result


@pytest.fixture
def mock_run() -> Iterator[mock.Mock]:
    """Patch the effectful collaborator (subprocess.run) once, in a fixture.

    Each test configures the returned mock's `return_value` / `side_effect` for
    the docker-info call it needs. Keeping the single `patch` here rather than
    inline in every test body is the mock-mechanism hygiene integration-lint
    enforces; detect_runtime (first-party) still runs for real.
    """
    with mock.patch("subprocess.run") as m:
        yield m


def describe_detect_runtime():
    """Integration tests for detect_runtime: real first-party, mocked docker."""

    def it_auto_resolves_to_runc_even_when_runsc_present(mock_run: mock.Mock):
        """auto picks the lightest sane runtime (runc) and never auto-escalates
        to gVisor -- runsc breaks the cage's ipset egress firewall."""
        mock_run.return_value = _docker_info_result({"runc": {}, "runsc": {}})
        assert detect_runtime("auto") == "runc"

    def it_auto_does_not_query_docker(mock_run: mock.Mock):
        """The default path short-circuits to runc without a docker info call."""
        mock_run.side_effect = AssertionError("queried docker")
        assert detect_runtime("auto") == "runc"
        assert detect_runtime("runc") == "runc"

    def it_returns_concrete_runtime_when_present(mock_run: mock.Mock):
        """A concrete request is honored when Docker has that runtime."""
        mock_run.return_value = _docker_info_result({"runc": {}, "runsc": {}})
        assert detect_runtime("runsc") == "runsc"

    def it_warns_and_falls_back_when_concrete_runtime_missing(mock_run: mock.Mock, capsys):
        """A concrete request for a missing runtime warns and falls back to runc."""
        mock_run.return_value = _docker_info_result({"runc": {}})
        assert detect_runtime("runsc") == "runc"
        captured = capsys.readouterr()
        assert "runsc" in captured.err
        assert "runc" in captured.err

    def it_resolves_kata_runtime_when_present(mock_run: mock.Mock):
        """kata-runtime is honored when Docker registers it."""
        mock_run.return_value = _docker_info_result({"runc": {}, "kata-runtime": {}})
        assert detect_runtime("kata-runtime") == "kata-runtime"

    def it_returns_runc_when_docker_info_fails(mock_run: mock.Mock):
        """A non-zero docker exit yields runc rather than raising."""
        mock_run.return_value = _docker_info_result({}, returncode=1)
        assert detect_runtime("auto") == "runc"

    def it_returns_runc_when_docker_missing(mock_run: mock.Mock):
        """A missing docker binary (OSError) yields runc."""
        mock_run.side_effect = FileNotFoundError("docker")
        assert detect_runtime("auto") == "runc"

    def it_returns_runc_on_malformed_json(mock_run: mock.Mock):
        """Unparseable docker output yields runc rather than raising."""
        result = mock.Mock()
        result.returncode = 0
        result.stdout = "not-json"
        mock_run.return_value = result
        assert detect_runtime("auto") == "runc"
