"""
Integration test for the UID-remap opt-out -- the per-run no-op derived build.

`devcontainer up` honors `updateRemoteUserUID` (default on for a non-root
`remoteUser`) by building an EXTRA derived image, tagged `...-uid`, whose only
job is to `usermod` the cage user to the host's uid/gid. It does that on every
`up`, and when the ids already match, the whole build is a no-op. Measured on a
warm host: 2.4s with the remap vs 2.0s without, reproducibly, three rounds.

The cage's `node` is uid/gid 1000 BY CONSTRUCTION -- the Dockerfile renames
whatever user the Playwright base image put at 1000 (`usermod -l node ...`,
`groupmod -n node ...`). So on any host whose user is also 1000 (the common
Linux single-user case) the remap can be turned off with no behavior change,
and on any other host it must stay on or bind-mounted files land wrong-owned.

OWN THE PRECONDITION -- the collaborator is the host process identity, so the
fixture below owns it rather than reading whoever the developer happens to be.
That is what makes these cells deterministic on a uid-1000 laptop AND in a CI
container running as root.
"""

import argparse
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from lamp_the_djinn.config import modify_config

pytestmark = pytest.mark.integration


def _bare_args() -> argparse.Namespace:
    """Minimal args namespace for modify_config (no extra features)."""
    return argparse.Namespace(
        build=False,
        ssh_key_file=None,
        gpg_key_id=None,
        git_user_name=None,
        git_user_email=None,
        gh_token=None,
        port=None,
        volume=None,
        env=None,
    )


@pytest.fixture
def config_for_host(tmp_path: Path) -> Callable[[int, int], dict]:
    """Build the config modify_config produces for a host running as uid:gid.

    The patch of the effectful collaborator lives here, not in a test body --
    the mock-mechanism hygiene the integration-lint rule enforces. It also has
    to be scoped this tightly: patching `os.getuid` for a whole test would break
    `tmp_path`, whose own setup stats its base dir for ownership. Taking
    `tmp_path` as a fixture dependency resolves it before any patching.
    """

    def build(uid: int, gid: int) -> dict:
        with (
            mock.patch("os.getuid", return_value=uid),
            mock.patch("os.getgid", return_value=gid),
        ):
            return modify_config({"mounts": [], "runArgs": []}, _bare_args(), tmp_path, trusted=False)

    return build


def describe_a_host_whose_ids_already_match_the_cage_user():
    """uid/gid 1000 -- the remap would rename node to the ids it already has."""

    def it_turns_the_uid_remap_off(config_for_host: Callable[[int, int], dict]):
        """`updateRemoteUserUID: false` is what skips the derived `-uid` build.

        Leaving it unset (the devcontainer default) is the slow path: the CLI
        builds and exports a whole extra image to apply a rename that changes
        nothing.
        """
        config = config_for_host(1000, 1000)

        assert config.get("updateRemoteUserUID") is False, (
            "a uid/gid-1000 host must opt out of the UID remap -- it is a pure no-op build there"
        )


def describe_a_host_whose_ids_differ_from_the_cage_user():
    """Anything but 1000:1000 -- the remap is doing real work and must stay."""

    @pytest.mark.parametrize(
        "uid,gid",
        [
            pytest.param(0, 0, id="root"),
            pytest.param(1001, 1001, id="second-user"),
            pytest.param(1000, 1001, id="matching-uid-only"),
            pytest.param(1001, 1000, id="matching-gid-only"),
        ],
    )
    def it_leaves_the_uid_remap_alone(uid: int, gid: int, config_for_host: Callable[[int, int], dict]):
        """Both ids must match before opting out.

        A partial match is not safe: the remap sets uid AND gid, so disabling it
        when only one lines up leaves bind-mounted files owned by the wrong
        group -- the exact breakage the remap exists to prevent.
        """
        config = config_for_host(uid, gid)

        assert "updateRemoteUserUID" not in config, (
            f"host {uid}:{gid} differs from the cage user, so the remap must stay enabled; "
            f"got updateRemoteUserUID={config.get('updateRemoteUserUID')!r}"
        )
