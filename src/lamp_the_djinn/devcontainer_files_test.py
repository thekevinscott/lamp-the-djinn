"""
Unit tests for extract_devcontainer_files, plus an assertion on the shipped
egress allowlist the extraction copies into every cage.
"""

from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.devcontainer_files import extract_devcontainer_files

pytestmark = pytest.mark.unit


def _fake_package_dir(root: Path) -> Path:
    """A stand-in for the package's devcontainer/ dir, with noise to be skipped."""
    pkg = root / "pkg-devcontainer"
    pkg.mkdir()
    (pkg / "devcontainer.json").write_text("{}")
    (pkg / "Dockerfile").write_text("FROM scratch\n")
    (pkg / "__init__.py").write_text("")
    (pkg / "stale.pyc").write_text("")
    (pkg / "subdir").mkdir()
    return pkg


def describe_extract_devcontainer_files():
    """The embedded template lands in this instance's cache dir, minus Python noise."""

    def it_copies_the_shipped_files_into_the_instance_dir(tmp_path: Path):
        pkg = _fake_package_dir(tmp_path)
        with (
            mock.patch("lamp_the_djinn.devcontainer_files.get_embedded_devcontainer_dir", return_value=pkg),
            mock.patch("lamp_the_djinn.devcontainer_files.get_workspace_dir", return_value=tmp_path / "ws"),
        ):
            workspace = extract_devcontainer_files("abc123")

        assert workspace == tmp_path / "ws"
        copied = {p.name for p in (workspace / ".devcontainer").iterdir()}
        assert copied == {"devcontainer.json", "Dockerfile"}

    def it_creates_the_devcontainer_dir_when_absent(tmp_path: Path):
        pkg = _fake_package_dir(tmp_path)
        with (
            mock.patch("lamp_the_djinn.devcontainer_files.get_embedded_devcontainer_dir", return_value=pkg),
            mock.patch("lamp_the_djinn.devcontainer_files.get_workspace_dir", return_value=tmp_path / "deep" / "ws"),
        ):
            workspace = extract_devcontainer_files("abc123")

        assert (workspace / ".devcontainer").is_dir()


def describe_shipped_firewall_whitelist():
    """The baked-in egress allowlist must not carry Claude's telemetry/auth hosts.

    The cage reaches the model only through the host proxy (the key never enters
    the cage), so api.anthropic.com is not needed inside; statsig.* / sentry.io
    are pure telemetry an isolation cage should not phone home to. Leaving them in
    also prints a `Failed to resolve statsig.anthropic.com` WARNING every run,
    since that host doesn't resolve off Anthropic's network.
    """

    _WHITELIST = Path(__file__).parent / "devcontainer" / "whitelisted-domains.txt"
    _FORBIDDEN = ("anthropic.com", "statsig.com", "sentry.io")

    def it_lists_no_anthropic_or_telemetry_domains():
        lines = [
            line.strip()
            for line in _WHITELIST.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        leaked = [d for d in lines if any(bad in d for bad in _FORBIDDEN)]
        assert not leaked, f"whitelist still ships telemetry/anthropic domains: {leaked}"
