"""
Unit tests for home_mount_parent_dirs: the dir math behind the post-`up` chown.

Style is pytest-describe (describe_/it_ blocks).
"""

from pathlib import Path

import pytest

from lamp_the_djinn.home_mounts import home_mount_parent_dirs

pytestmark = pytest.mark.unit


def describe_home_mount_parent_dirs():
    """Which cage-side dirs ltd must re-own after a home-nested `-v` mount.

    Docker creates the absent parents of a home-nested mount owned by ROOT, so
    the cage user can't write siblings (pi's `mkdir ~/.pi/agent/sessions/...`
    fails with EACCES). This is the decision -- which dirs -- that ltd hands to
    `docker exec --user root chown` once the cage is up. The e2e suite pins the
    real EACCES; here we pin the dir math without Docker."""

    def it_lists_the_intermediate_parents_of_a_home_nested_mount():
        home = Path("/home/duncan")
        # `ltd -v ~/.pi/agent/models.json ...` -> these two dirs are made by Docker.
        dirs = home_mount_parent_dirs([str(home / ".pi" / "agent" / "models.json")], home)
        assert dirs == ["/home/node/.pi", "/home/node/.pi/agent"]

    def it_returns_nothing_for_a_top_level_home_mount():
        # `~/.pi` maps to /home/node/.pi -- its only parent IS the cage home,
        # which already exists owned by the cage user. Nothing to re-own.
        home = Path("/home/duncan")
        assert home_mount_parent_dirs([str(home / ".pi")], home) == []

    def it_ignores_a_path_outside_the_host_home():
        # Path-identity mounts (outside home) land on dirs the host already owns.
        assert home_mount_parent_dirs(["/mnt/data/sub/file"], Path("/home/duncan")) == []

    def it_ignores_an_explicit_host_colon_container_mount():
        # The user owns an explicit layout; ltd does not second-guess it.
        home = Path("/home/duncan")
        assert home_mount_parent_dirs([f"{home}/.pi/agent/models.json:/x/y/z.json"], home) == []

    def it_dedupes_shared_parents_across_multiple_file_mounts():
        home = Path("/home/duncan")
        dirs = home_mount_parent_dirs(
            [str(home / ".pi" / "agent" / "models.json"), str(home / ".pi" / "agent" / "settings.json")],
            home,
        )
        assert dirs == ["/home/node/.pi", "/home/node/.pi/agent"]
