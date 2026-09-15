"""Unit tests for staging a disposable copy of the host keyring."""

from pathlib import Path

import pytest

from lamp_the_djinn.gnupg_config import stage_gnupg_config

pytestmark = pytest.mark.unit


def describe_staging_the_host_keyring():
    def it_copies_the_keyring_with_gpg_safe_permissions(tmp_path: Path):
        home = tmp_path / "home"
        (home / ".gnupg" / "private-keys-v1.d").mkdir(parents=True)
        (home / ".gnupg" / "pubring.kbx").write_bytes(b"kbx")
        (home / ".gnupg" / "pubring.kbx").chmod(0o644)
        dest = tmp_path / "stage"

        stage_gnupg_config(home, dest)

        assert (dest / "pubring.kbx").read_bytes() == b"kbx"
        assert (dest / "pubring.kbx").stat().st_mode & 0o777 == 0o600
        assert (dest / "private-keys-v1.d").stat().st_mode & 0o777 == 0o700
        assert dest.stat().st_mode & 0o777 == 0o700

    def it_is_a_noop_for_a_missing_host_keyring(tmp_path: Path):
        dest = tmp_path / "stage"

        stage_gnupg_config(tmp_path / "empty-home", dest)

        assert list(dest.iterdir()) == []
