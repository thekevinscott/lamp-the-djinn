"""Remove the cage container(s) a run created."""

import subprocess


def teardown_cage(id_label: str) -> None:
    """Force-remove the cage container(s) carrying this instance's label.

    `devcontainer up` starts a PERSISTENT container; the agent runs inside it and
    exits, but the container keeps running. Each ltd run uses a fresh instance id,
    so the cage is never reused -- leaving it up just orphans one container per
    run. There is no `devcontainer down` for a single instance, so we resolve the
    labelled container id(s) and `docker rm -f` them. Best-effort and quiet: a
    teardown failure must not mask the command's own exit code.
    """
    found = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={id_label}"],
        capture_output=True,
        text=True,
    )
    ids = found.stdout.split()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, text=True)
