"""
Integration tests for the release manifest's repository URL.

The real collaborator is the filesystem: `pyproject.toml` is read from the repo
root, not mocked. putitoutthere compares `[project.urls]` against
GITHUB_REPOSITORY before it will publish, and a stale slug there aborts the
release job outright (PIOT_REPO_URL_MISMATCH).
"""

from pathlib import Path

import pytest
import tomllib

pytestmark = pytest.mark.integration

GITHUB_SLUG = "thekevinscott/lamp-the-djinn"
REPO_ROOT = Path(__file__).resolve().parents[2]


def describe_pyproject_urls():
    def it_points_project_urls_at_the_github_repository():
        manifest = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        urls = manifest["project"]["urls"]

        expected = f"https://github.com/{GITHUB_SLUG}"
        assert urls["Repository"] == expected
        assert urls["Homepage"] == expected
