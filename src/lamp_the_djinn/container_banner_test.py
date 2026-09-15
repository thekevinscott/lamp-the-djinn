"""Unit tests for print_container_info: the startup provenance banner."""

from unittest import mock

import pytest

from lamp_the_djinn.container_banner import print_container_info

pytestmark = pytest.mark.unit


def describe_print_container_info():
    """The banner renders the labels the info lookup returned."""

    def it_names_the_registry_for_a_pulled_image(capsys: pytest.CaptureFixture):
        info = {"build_time": "2026-01-02T03:04:05Z", "source": "ghcr.io"}
        with mock.patch("lamp_the_djinn.container_banner.get_container_info", return_value=info):
            print_container_info("img")

        out = capsys.readouterr().out
        assert "Container image: img" in out
        assert "GitHub Container Registry (ghcr.io)" in out
        assert "2026-01-02T03:04:05Z" in out

    def it_calls_anything_else_a_local_build(capsys: pytest.CaptureFixture):
        info = {"build_time": "unknown", "source": "local"}
        with mock.patch("lamp_the_djinn.container_banner.get_container_info", return_value=info):
            print_container_info("img")

        out = capsys.readouterr().out
        assert "Local build" in out
        assert "Built: Unknown" in out
