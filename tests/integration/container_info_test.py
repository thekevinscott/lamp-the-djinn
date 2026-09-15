"""
Integration tests for get_container_info.

The collaborator (docker inspect via subprocess.run) is mocked out -- no real
container is started -- so this is the integration tier, not e2e.
"""

from collections.abc import Iterator
from unittest import mock

import pytest

from lamp_the_djinn.container_info import get_container_info

pytestmark = pytest.mark.integration


@pytest.fixture
def mock_run() -> Iterator[mock.Mock]:
    """Patch the effectful collaborator (subprocess.run) once, in a fixture.

    Each test sets `mock_run.return_value.stdout` to the docker-inspect output it
    needs; get_container_info (first-party) parses it for real. The single patch
    lives here, not inline in each test body -- the integration-lint hygiene rule.
    """
    with mock.patch("subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="")
        yield m


def describe_get_container_info():
    """Parsing docker-inspect label output into build_time/source."""

    def it_parses_ghcr_image_labels(mock_run: mock.Mock):
        """Test parsing labels from a ghcr.io built image."""
        mock_run.return_value = mock.Mock(returncode=0, stdout="2025-01-15T10:30:00Z|ghcr.io")
        info = get_container_info("ghcr.io/test/image:latest")
        assert info["build_time"] == "2025-01-15T10:30:00Z"
        assert info["source"] == "ghcr.io"

    def it_parses_local_image_labels(mock_run: mock.Mock):
        """Test parsing labels from a locally built image."""
        mock_run.return_value = mock.Mock(returncode=0, stdout="2025-01-15T10:30:00Z|local")
        info = get_container_info("my-local-image:latest")
        assert info["build_time"] == "2025-01-15T10:30:00Z"
        assert info["source"] == "local"

    def it_handles_missing_labels(mock_run: mock.Mock):
        """Test handling images without labels."""
        mock_run.return_value = mock.Mock(returncode=0, stdout="|")
        info = get_container_info("image-without-labels:latest")
        assert info["build_time"] == "unknown"
        assert info["source"] == "local"

    def it_handles_docker_inspect_failure(mock_run: mock.Mock):
        """Test handling when docker inspect fails."""
        mock_run.return_value = mock.Mock(returncode=1, stdout="")
        info = get_container_info("nonexistent:latest")
        assert info["build_time"] == "unknown"
        assert info["source"] == "unknown"

    def it_handles_partial_labels(mock_run: mock.Mock):
        """Test handling when only build_time label exists."""
        mock_run.return_value = mock.Mock(returncode=0, stdout="2025-01-15T10:30:00Z|")
        info = get_container_info("partial-labels:latest")
        assert info["build_time"] == "2025-01-15T10:30:00Z"
        assert info["source"] == "local"
