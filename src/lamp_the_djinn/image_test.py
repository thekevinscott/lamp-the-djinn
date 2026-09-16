"""Unit tests for pull_docker_image_if_needed. Docker is mocked out."""

from unittest import mock

import pytest

from lamp_the_djinn.image import IMAGE_NAME, pull_docker_image_if_needed

pytestmark = pytest.mark.unit


def describe_pull_docker_image_if_needed():
    """Pull only when the host does not already have the image."""

    def it_skips_the_pull_when_the_image_is_present():
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            pull_docker_image_if_needed()
        assert run.call_count == 1  # the inspect only

    def it_pulls_when_the_image_is_absent():
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)) as run:
            pull_docker_image_if_needed()

        pull = run.call_args_list[-1].args[0]
        assert pull == ["docker", "pull", IMAGE_NAME]
        # check=True so the caller can catch the failure and fall back to --build.
        assert run.call_args_list[-1].kwargs["check"] is True


def describe_image_name():
    """The published cage image."""

    def it_points_at_the_current_org():
        # Repo moved thekevinbot -> thekevinscott (#90); pin the exact owner so a
        # future move can't leave this drifted the way #94 did.
        assert IMAGE_NAME == "ghcr.io/thekevinscott/lamp-the-djinn:latest"
