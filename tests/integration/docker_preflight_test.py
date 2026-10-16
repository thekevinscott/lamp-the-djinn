"""
Integration tier for the Docker preflight: the source-tree `ltd` with no
`docker` on PATH must print the banner and exit 1, not a traceback.

OWN THE PRECONDITION: PATH holds only the venv bin and an empty directory, so
`docker` is unreachable regardless of the host. HOME is isolated so nothing
the run writes lands in the developer's real home.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def describe_running_ltd_without_docker_on_path():
    """A missing docker binary is reported like a stopped daemon: banner, exit 1."""

    def it_prints_the_not_installed_banner_and_exits_one(tmp_path: Path):
        ltd = Path(sys.prefix) / "bin" / "ltd"
        if not ltd.exists():
            pytest.skip("project venv has no `ltd` console script (run `uv sync`)")
        empty = tmp_path / "bin"
        empty.mkdir()
        path = f"{ltd.parent}{os.pathsep}{empty}"
        assert shutil.which("docker", path=path) is None
        env = {**os.environ, "PATH": path, "HOME": str(tmp_path)}

        result = subprocess.run([str(ltd), "echo", "hi"], env=env, capture_output=True, text=True)

        assert "Traceback" not in result.stderr
        assert "Docker is not installed" in result.stderr
        assert result.returncode == 1
