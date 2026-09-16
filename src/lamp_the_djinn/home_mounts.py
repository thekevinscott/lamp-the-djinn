"""Which cage-side dirs Docker creates as root for home-nested bind mounts."""

from pathlib import Path


def home_mount_parent_dirs(volumes: list[str] | None, host_home: Path) -> list[str]:
    """Cage-side dirs Docker auto-creates (owned by ROOT) for home-nested mounts.

    A bare `-v` under the host home is remapped to the same relative path under
    the cage home (`~/.pi/agent/models.json` -> `/home/node/.pi/agent/...`; see
    modify_config). Docker, mounting into a path whose parent dirs are absent
    from the image, creates that whole parent chain owned by ROOT -- so the cage
    user (`node`) cannot write siblings, and pi's first act,
    `mkdir ~/.pi/agent/sessions/...`, dies with EACCES. ltd re-owns these
    intermediate dirs to `node` from the host once the cage is up (see
    fix_mount_dir_ownership); it never touches the mount target itself (the bind
    point) nor the host file behind it.

    Returns the sorted, de-duplicated cage-side dirs to re-own -- the parents of
    each home-mapped mount target, from its containing dir up to (but excluding)
    the cage home. Empty when nothing nests below the cage home. Explicit
    `host:container` mounts are skipped: the user owns that layout.
    """
    cage_home = Path("/home/node")
    dirs: set[str] = set()
    for vol in volumes or []:
        if ":" in vol:
            continue
        host_path = Path(vol).resolve()
        if not (host_path == host_home or host_home in host_path.parents):
            continue
        target = cage_home / host_path.relative_to(host_home)
        parent = target.parent
        while parent != cage_home and cage_home in parent.parents:
            dirs.add(str(parent))
            parent = parent.parent
    return sorted(dirs)
