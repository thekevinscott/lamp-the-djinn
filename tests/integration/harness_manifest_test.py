"""
Integration test for record_manifest against a real, isolated HOME.

The manifest is installed on the host by scripts/refresh-harness-cache.sh, so
an option value written there (a registry URL, a Python version) becomes a
host-side install. The collaborator is the host filesystem under a
monkeypatched HOME.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.manifest import record_manifest

pytestmark = pytest.mark.integration


@pytest.fixture
def home(tmp_path: Path) -> Iterator[Path]:
    """An isolated $HOME, scoped by patch.dict and restored on teardown."""
    with mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        yield tmp_path


def describe_record_manifest():
    """Only package specs reach the harness manifest."""

    @pytest.mark.parametrize(
        ("command", "spec"),
        [
            (["npx", "--registry", "http://x", "pkg"], "pkg"),
            (["npx", "-p", "left-pad", "left-pad-bin"], "left-pad"),
            (["npm", "exec", "--package=cowsay", "--", "cowsay"], "cowsay"),
            (["uvx", "--python", "3.12", "ruff"], "ruff"),
            (["uvx", "--from", "httpie", "http"], "httpie"),
            (["uv", "tool", "run", "-p", "3.12", "ruff"], "ruff"),
        ],
    )
    def it_records_the_package_spec_not_an_option_value(home: Path, command: list[str], spec: str):
        record_manifest(command)
        manifest = home / ".cache" / "lamp-the-djinn" / "harness-manifest.txt"
        assert manifest.read_text().splitlines() == [spec]
