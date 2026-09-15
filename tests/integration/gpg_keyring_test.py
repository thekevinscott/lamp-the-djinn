"""
Integration test for the staged GPG keyring -- the read-only GNUPGHOME bug.

The collaborator here is the host filesystem: a real keyring-shaped directory on
disk, staged for real by `stage_gnupg_config`, then handed to `modify_config` to
see what mount it produces. No Docker, no container.

Why this pairs with the e2e (tests/e2e/gpg_signing_test.py): the e2e proves the
deployed `ltd` can actually sign a commit; this proves, in milliseconds, the two
decisions behind it -- the keyring is COPIED (host untouched, permissions gpg
will accept) and mounted WRITABLE (gpg-agent needs to create its socket and
lockfiles inside GNUPGHOME). On the old code -- a `readonly` bind of
`${localEnv:HOME}/.gnupg` -- the mount assertions go red.
"""

import argparse
import stat
from pathlib import Path

import pytest

from lamp_the_djinn.cli import modify_config, stage_gnupg_config

pytestmark = pytest.mark.integration

KEY_ID = "C567F8478F289CC4"


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        build=False,
        ssh_key_file=None,
        gpg_key_id=None,
        git_user_name=None,
        git_user_email=None,
        gh_token=None,
        port=None,
        volume=None,
        env=None,
        allow_domains_file=None,
        trusted=False,
        memory=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _host_keyring(home: Path) -> Path:
    """A realistic host `~/.gnupg`: keybox, trustdb, and private key material."""
    gnupg = home / ".gnupg"
    (gnupg / "private-keys-v1.d").mkdir(parents=True)
    (gnupg / "pubring.kbx").write_bytes(b"kbx")
    (gnupg / "trustdb.gpg").write_bytes(b"trust")
    (gnupg / "gpg.conf").write_text("use-agent\n")
    (gnupg / "private-keys-v1.d" / "ABCDEF.key").write_bytes(b"secret")
    return gnupg


def _gpg_mounts(config: dict) -> list[str]:
    return [m for m in config.get("mounts", []) if "/home/node/.gnupg" in m]


def describe_stage_gnupg_config():
    """The disposable copy of the host keyring."""

    def it_copies_the_keyring_contents(tmp_path: Path):
        home = tmp_path / "home"
        _host_keyring(home)
        dest = tmp_path / "stage"

        stage_gnupg_config(home, dest)

        assert (dest / "pubring.kbx").read_bytes() == b"kbx"
        assert (dest / "trustdb.gpg").read_bytes() == b"trust"
        assert (dest / "private-keys-v1.d" / "ABCDEF.key").read_bytes() == b"secret"

    def it_applies_the_permissions_gpg_demands(tmp_path: Path):
        """700 on dirs, 600 on files -- gpg refuses a keyring with looser modes."""
        home = tmp_path / "home"
        gnupg = _host_keyring(home)
        (gnupg / "pubring.kbx").chmod(0o644)
        dest = tmp_path / "stage"

        stage_gnupg_config(home, dest)

        assert stat.S_IMODE(dest.stat().st_mode) == 0o700
        assert stat.S_IMODE((dest / "private-keys-v1.d").stat().st_mode) == 0o700
        assert stat.S_IMODE((dest / "pubring.kbx").stat().st_mode) == 0o600
        assert stat.S_IMODE((dest / "private-keys-v1.d" / "ABCDEF.key").stat().st_mode) == 0o600

    def it_leaves_the_host_keyring_untouched(tmp_path: Path):
        home = tmp_path / "home"
        gnupg = _host_keyring(home)
        before = sorted(p.name for p in gnupg.iterdir())
        dest = tmp_path / "stage"

        stage_gnupg_config(home, dest)

        assert sorted(p.name for p in gnupg.iterdir()) == before

    def it_tolerates_a_missing_host_keyring(tmp_path: Path):
        """No host `~/.gnupg` must not crash the run -- gpg reports the missing
        key itself, which is a far clearer failure than a stage-time traceback."""
        dest = tmp_path / "stage"

        stage_gnupg_config(tmp_path / "home", dest)

        assert dest.is_dir()


def describe_the_cage_keyring_mount():
    """What `--gpg-key-id` puts in the devcontainer config."""

    def it_mounts_the_staged_copy_writable(tmp_path: Path):
        """gpg-agent creates sockets/lockfiles inside GNUPGHOME, so a read-only
        mount leaves it unable to start: "signing failed: No agent running"."""
        stage = tmp_path / "gnupg-stage"
        stage.mkdir()

        config = modify_config(
            {"mounts": [], "runArgs": []},
            _args(gpg_key_id=KEY_ID),
            tmp_path,
            gnupg_stage_dir=stage,
        )

        mounts = _gpg_mounts(config)
        assert mounts == [f"source={stage},target=/home/node/.gnupg,type=bind"], mounts
        assert not any("readonly" in m for m in mounts), f"the cage keyring must be writable: {mounts}"

    def it_never_binds_the_host_keyring(tmp_path: Path):
        """The real `~/.gnupg` must not appear as a mount source at all -- a
        writable bind of it would let the agent corrupt or delete host keys."""
        stage = tmp_path / "gnupg-stage"
        stage.mkdir()

        config = modify_config(
            {"mounts": ["source=${localEnv:HOME}/.gnupg,target=/home/node/.gnupg,type=bind"], "runArgs": []},
            _args(gpg_key_id=KEY_ID),
            tmp_path,
            gnupg_stage_dir=stage,
        )

        assert not any("localEnv:HOME}/.gnupg" in m for m in config["mounts"]), config["mounts"]

    def it_adds_no_keyring_mount_without_the_flag(tmp_path: Path):
        config = modify_config({"mounts": [], "runArgs": []}, _args(), tmp_path)

        assert _gpg_mounts(config) == []
