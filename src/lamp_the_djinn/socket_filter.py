"""A ``shutil.copytree`` ignore-callable that drops sockets."""

import os
import stat


def ignore_sockets(directory: str, names: list[str]) -> set[str]:
    """Names under ``directory`` that copytree must skip: sockets and unstattable entries."""
    ignored = set()
    for name in names:
        try:
            if stat.S_ISSOCK(os.lstat(os.path.join(directory, name)).st_mode):
                ignored.add(name)
        except OSError:
            ignored.add(name)
    return ignored
