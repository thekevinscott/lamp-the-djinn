"""
Unit tests for the derived host paths: the embedded devcontainer dir ships
inside the package, and each run gets its own workspace dir.
"""

from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.paths import get_embedded_devcontainer_dir, get_workspace_dir

pytestmark = pytest.mark.unit


def describe_get_embedded_devcontainer_dir():
    """The devcontainer template is package data, not a host path."""

    def it_points_inside_the_installed_package():
        d = get_embedded_devcontainer_dir()
        assert d.name == "devcontainer"
        assert d.parent.name == "lamp_the_djinn"


def describe_get_workspace_dir():
    """Each instance id gets its own cache dir, so concurrent runs cannot collide."""

    def it_namespaces_the_cache_dir_by_instance_id(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            assert get_workspace_dir("abc123") == tmp_path / ".cache" / "lamp-the-djinn" / "workspace-abc123"

    def it_gives_different_instances_different_dirs(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            assert get_workspace_dir("one") != get_workspace_dir("two")
