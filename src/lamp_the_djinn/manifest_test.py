"""
Unit tests for record_manifest: conservative package-spec extraction from
package-runner commands, written to the cache-freshness manifest.

Style is pytest-describe (describe_/it_ blocks).
"""

from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.manifest import record_manifest

pytestmark = pytest.mark.unit


def describe_record_manifest():
    """Conservative package-spec extraction from package-runner commands."""

    def it_records_npx_spec(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            record_manifest(["npx", "@anthropic/claude"])
        assert "@anthropic/claude" in self_check(tmp_path)

    def it_records_uvx_spec(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            record_manifest(["uvx", "aider"])
        assert "aider" in self_check(tmp_path)

    def it_skips_flags_to_find_the_package(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            record_manifest(["npx", "-y", "@openai/codex"])
        assert "@openai/codex" in self_check(tmp_path)

    def it_records_npm_install_and_uv_tool(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            record_manifest(["npm", "install", "prettier"])
            record_manifest(["uv", "tool", "install", "black"])
        lines = self_check(tmp_path)
        assert "prettier" in lines
        assert "black" in lines

    def it_ignores_non_runner_commands(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            record_manifest(["claude", "-p", "hi"])
            record_manifest([])
        assert self_check(tmp_path) == []

    def it_dedupes_repeated_specs(tmp_path: Path):
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            record_manifest(["uvx", "aider"])
            record_manifest(["uvx", "aider"])
        assert self_check(tmp_path).count("aider") == 1


def self_check(home: Path) -> list[str]:
    """Read manifest lines under a mocked HOME (helper for record_manifest tests)."""
    manifest = home / ".cache" / "lamp-the-djinn" / "harness-manifest.txt"
    if not manifest.exists():
        return []
    return manifest.read_text().splitlines()
