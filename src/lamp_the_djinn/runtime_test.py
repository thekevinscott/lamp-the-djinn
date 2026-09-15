"""
Unit tests for detect_runtime. The Docker query is mocked out; the integration
tier (tests/integration/runtime_test.py) covers the same decision against a
realistic `docker info` payload.
"""

from unittest import mock

import pytest

from lamp_the_djinn.runtime import detect_runtime

pytestmark = pytest.mark.unit


def _docker_info(stdout: str, returncode: int = 0) -> mock.Mock:
    return mock.Mock(stdout=stdout, returncode=returncode)


def describe_detect_runtime():
    """ "auto" never queries Docker; a concrete request is validated against it."""

    def it_resolves_auto_to_runc_without_asking_docker():
        with mock.patch("subprocess.run") as run:
            assert detect_runtime("auto") == "runc"
        run.assert_not_called()

    def it_short_circuits_an_explicit_runc_request():
        with mock.patch("subprocess.run") as run:
            assert detect_runtime("runc") == "runc"
        run.assert_not_called()

    def it_honors_a_registered_runtime():
        with mock.patch("subprocess.run", return_value=_docker_info('{"runsc": {}, "runc": {}}')):
            assert detect_runtime("runsc") == "runsc"

    def it_falls_back_to_runc_when_the_runtime_is_absent():
        with mock.patch("subprocess.run", return_value=_docker_info('{"runc": {}}')):
            assert detect_runtime("kata-runtime") == "runc"

    def it_falls_back_to_runc_when_docker_fails():
        with mock.patch("subprocess.run", return_value=_docker_info("", returncode=1)):
            assert detect_runtime("runsc") == "runc"

    def it_falls_back_to_runc_when_docker_is_missing():
        with mock.patch("subprocess.run", side_effect=OSError("no docker")):
            assert detect_runtime("runsc") == "runc"

    def it_falls_back_to_runc_on_malformed_output():
        with mock.patch("subprocess.run", return_value=_docker_info("not json")):
            assert detect_runtime("runsc") == "runc"

    def it_falls_back_to_runc_when_runtimes_is_not_a_mapping():
        with mock.patch("subprocess.run", return_value=_docker_info("[]")):
            assert detect_runtime("runsc") == "runc"
