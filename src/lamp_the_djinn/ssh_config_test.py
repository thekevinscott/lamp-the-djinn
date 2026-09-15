"""Unit tests for generate_ssh_config: the cage's GitHub SSH client config."""

from pathlib import Path

import pytest

from lamp_the_djinn.ssh_config import generate_ssh_config

pytestmark = pytest.mark.unit


def describe_generate_ssh_config():
    """The config points GitHub at the key as mounted inside the cage."""

    def it_references_the_key_at_its_cage_path(tmp_path: Path):
        path = generate_ssh_config(tmp_path, "id_ed25519_robot")
        body = path.read_text()
        assert "Host github.com" in body
        assert "IdentityFile /home/node/.ssh/id_ed25519_robot" in body
        assert "IdentitiesOnly yes" in body

    def it_writes_ssh_readable_permissions(tmp_path: Path):
        # SSH refuses a config it considers group/world-writable.
        path = generate_ssh_config(tmp_path, "key")
        assert path.stat().st_mode & 0o777 == 0o644
