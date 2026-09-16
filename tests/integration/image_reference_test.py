"""Pin every functional copy of the cage image reference to the current owner.

The repo moved thekevinbot -> thekevinscott (#90), but the cage image name has
three independent copies that must agree: `image.py`'s IMAGE_NAME (what ltd
pre-pulls), the embedded devcontainer.json's `image` field (what the
devcontainers CLI itself pulls/runs when not --build), and fly/fly.toml (the
fly backend, reusing the same published image per fly/README.md). If the first
two disagree, ltd can pre-pull one image successfully and then hand the
devcontainers CLI a config pointing at a different, possibly-nonexistent one,
which is not caught by ltd's own pull-failure fallback (#94). This test reads
each real file so a future org move can't leave any copy drifted.
"""

import json
import re
from pathlib import Path

import pytest

from lamp_the_djinn.image import IMAGE_NAME
from lamp_the_djinn.paths import get_embedded_devcontainer_dir

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def _current_repo_slug() -> str:
    """The github.com/<owner>/<repo> slug pyproject.toml declares as canonical."""
    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text()
    match = re.search(r'Repository = "https://github\.com/([^"]+)"', pyproject_text)
    assert match, "pyproject.toml has no [project.urls] Repository entry"
    return match.group(1)


def describe_image_name():
    """IMAGE_NAME must track wherever docker-publish.yml actually publishes."""

    def it_matches_the_current_repo_owner():
        assert IMAGE_NAME == f"ghcr.io/{_current_repo_slug()}:latest"


def describe_embedded_devcontainer_json():
    """The shipped devcontainer.json's `image` field, used when not --build."""

    def it_matches_image_py():
        devcontainer_json = get_embedded_devcontainer_dir() / "devcontainer.json"
        config = json.loads(devcontainer_json.read_text())
        assert config["image"] == IMAGE_NAME


def describe_fly_toml():
    """The fly backend reuses the same published image (fly/README.md)."""

    def it_matches_image_py():
        fly_toml_text = (REPO_ROOT / "fly" / "fly.toml").read_text()
        assert f'image = "{IMAGE_NAME}"' in fly_toml_text
