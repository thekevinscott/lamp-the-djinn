"""Re-own, from the host, the root-owned dirs Docker created for home-nested mounts."""

import subprocess
import sys


def fix_mount_dir_ownership(id_label: str, dirs: list[str], debug: bool = False) -> None:
    """Re-own to the cage user the root-owned parent dirs Docker created for
    home-nested bind mounts (see home_mount_parent_dirs).

    Done from the HOST via the Docker daemon -- ltd already has Docker access --
    NOT from inside the cage. That is the security-load-bearing choice: it keeps
    the untrusted agent with NO standing root primitive. Putting a `sudo chown`
    in the cage's postStartCommand instead would force `chown` onto the cage's
    passwordless-sudo allowlist (today only init-firewall.sh / ipset), handing
    the agent a general root-owns-anything escalation. Non-recursive on purpose:
    it touches only the dirs themselves, never the bind-mounted file (chowning
    that would change the HOST file's owner through the shared inode).

    Best-effort: a teardown/run must not be aborted by a chown hiccup; surface
    failures only in debug.
    """
    if not dirs:
        return
    found = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={id_label}"],
        capture_output=True,
        text=True,
    )
    ids = found.stdout.split()
    if not ids:
        return
    result = subprocess.run(
        ["docker", "exec", "--user", "root", ids[0], "chown", "node:node", *dirs],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and debug:
        print(f"Could not re-own mount parent dirs {dirs}: {result.stderr.strip()}", file=sys.stderr)
