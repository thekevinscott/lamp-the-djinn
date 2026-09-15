"""Stage a disposable, writable copy of the host ``~/.gnupg`` for the cage."""

import shutil
from pathlib import Path

from .socket_filter import ignore_sockets


def stage_gnupg_config(home: Path, dest: Path) -> None:
    """Copy the host ``~/.gnupg`` into ``dest`` as a disposable, writable keyring.

    gpg-agent creates sockets and lockfiles INSIDE ``GNUPGHOME``, so a read-only
    bind of the host keyring leaves it unable to start ("signing failed: No agent
    running"), and a read-write bind would let the untrusted agent corrupt or
    delete the host's real keys. A copy gives a working agent and an untouched
    host keyring; it is deleted when the cage comes down.

    Live agent sockets in the source are skipped (they are not copyable, and the
    cage's own agent makes its own). Permissions are forced to 700 dirs / 600
    files -- gpg refuses a keyring with looser modes.
    """
    src = home / ".gnupg"
    dest.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True, ignore=ignore_sockets, ignore_dangling_symlinks=True)

    dest.chmod(0o700)
    for path in dest.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
