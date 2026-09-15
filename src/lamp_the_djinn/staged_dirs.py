"""Delete the per-run staging dirs once the cage is down."""

import shutil
from pathlib import Path


def discard_staged_dirs(dirs: list[Path]) -> None:
    """Delete per-run staging dirs once the cage is down.

    The staged GPG keyring is a copy of private key material; leaving it in
    ~/.cache after every run would accumulate secrets on disk. Best-effort: a
    failed cleanup must not mask the command's own exit code.
    """
    for path in dirs:
        shutil.rmtree(path, ignore_errors=True)
