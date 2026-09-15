"""Unit tests for discarding per-run staging dirs."""

from pathlib import Path

import pytest

from lamp_the_djinn.staged_dirs import discard_staged_dirs

pytestmark = pytest.mark.unit


def describe_discard_staged_dirs():
    """The staged keyring holds private key material, so it must not survive."""

    def it_removes_the_staged_dirs(tmp_path: Path):
        stage = tmp_path / "gnupg-stage"
        (stage / "private-keys-v1.d").mkdir(parents=True)
        (stage / "private-keys-v1.d" / "k.key").write_bytes(b"secret")

        discard_staged_dirs([stage])

        assert not stage.exists()

    def it_ignores_dirs_that_are_already_gone(tmp_path: Path):
        discard_staged_dirs([tmp_path / "never-existed"])  # must not raise
