"""Unit tests for get_container_info. `docker image inspect` is mocked out."""

from unittest import mock

import pytest

from lamp_the_djinn.container_info import get_container_info

pytestmark = pytest.mark.unit


def describe_get_container_info():
    """Provenance comes off the image's OCI labels, with safe fallbacks."""

    def it_parses_the_label_pair():
        out = mock.Mock(returncode=0, stdout="2026-01-02T03:04:05Z|ghcr.io\n")
        with mock.patch("subprocess.run", return_value=out):
            assert get_container_info("img") == {"build_time": "2026-01-02T03:04:05Z", "source": "ghcr.io"}

    def it_reports_unknown_when_inspect_fails():
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout="")):
            assert get_container_info("img") == {"build_time": "unknown", "source": "unknown"}

    def it_defaults_a_blank_source_to_local():
        """A locally built image carries no source label, so it reads as `local`."""
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="2026-01-02T03:04:05Z|\n")):
            assert get_container_info("img")["source"] == "local"

    def it_defaults_a_blank_build_time_to_unknown():
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="|ghcr.io\n")):
            assert get_container_info("img")["build_time"] == "unknown"
