"""Bring the cage up, run the command in it, and always tear it down."""

import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from .command import resolve_command
from .mount_ownership import fix_mount_dir_ownership
from .staged_dirs import discard_staged_dirs
from .teardown import teardown_cage


def run_devcontainer(
    config_path: Path,
    workspace_dir: Path,
    project_dir: Path,
    command: list[str] | None = None,
    shell_cmd: str | None = None,
    safe_mode: bool = False,
    instance_id: str | None = None,
    mount_parent_dirs: list[str] | None = None,
    debug: bool = False,
    discard_dirs: list[Path] | None = None,
) -> None:
    """Run the devcontainer with the resolved command.

    The command is whatever the user typed after ltd's own options. Precedence:
    explicit command > --shell CMD > default claude (see resolve_command).

    Each invocation uses a unique instance ID for both the config directory
    and container label, allowing multiple clanker instances to run simultaneously.
    """
    devcontainer_cmd = ["npx", "-y", "@devcontainers/cli"]

    # Use provided instance ID or generate one (for backwards compatibility)
    if instance_id is None:
        instance_id = uuid.uuid4().hex[:12]
    id_label = f"clanker.instance={instance_id}"

    run_cmd = resolve_command(command or [], shell_cmd, safe_mode)

    up_cmd = devcontainer_cmd + [
        "up",
        "--workspace-folder",
        str(project_dir),
        "--config",
        str(config_path),
        "--id-label",
        id_label,
    ]

    exec_cmd = (
        devcontainer_cmd
        + [
            "exec",
            "--workspace-folder",
            str(project_dir),
            "--config",
            str(config_path),
            "--id-label",
            id_label,
        ]
        + run_cmd
    )

    # Run both `up` and the agent as CHILDREN (the agent inherits our stdio, so an
    # interactive TUI gets clean TTY passthrough), then ALWAYS tear the cage down
    # -- we cannot execvp here or no teardown code path would ever run and every
    # cage would leak.
    #
    # A clean exit reaches the `finally`, but two ways out do NOT: SIGTERM (a
    # `kill`) and SIGHUP (the user closes their terminal) terminate ltd outright,
    # and a `finally` does not run when the default signal action fires -- and an
    # interactive session is exactly when those arrive. So we install handlers
    # that kill whatever child is live and tear the cage down ON the signal path
    # before exiting. The signals can also land during `up` (the cage is created
    # partway through it); if no handler were armed yet, ltd would die and the
    # orphaned `up` would finish bringing the cage up -- a leak. So arm them
    # BEFORE `up`, covering the whole lifecycle.
    #
    # SIGINT is different: a terminal Ctrl-C reaches the child's process group
    # directly, so the agent handles it; ltd just ignores it and survives long
    # enough to reach the normal teardown and propagate the child's exit code.
    child: subprocess.Popen | None = None

    def _on_terminating_signal(signum, _frame):
        if child is not None and child.poll() is None:
            child.terminate()
        teardown_cage(id_label)
        discard_staged_dirs(discard_dirs or [])
        # We are on the signal path; skip the rest of the function and report the
        # signal the way a shell would (128 + N).
        os._exit(128 + signum)

    previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    previous_sigterm = signal.signal(signal.SIGTERM, _on_terminating_signal)
    previous_sighup = signal.signal(signal.SIGHUP, _on_terminating_signal)
    try:
        if debug:
            print(f"Starting devcontainer (instance {instance_id}, command: {' '.join(run_cmd)})...")
            child = subprocess.Popen(up_cmd)
            child.wait()
            if child.returncode != 0:
                raise subprocess.CalledProcessError(child.returncode, up_cmd)
        else:
            # Quiet (default): hide the build/firewall/devcontainer noise so only
            # the agent's own output reaches the terminal. Show a transient status
            # while the cage comes up (a first build can be slow), then erase it so
            # it doesn't linger above the agent's output. TTY only -- piped output
            # stays clean. Surface the full output if the up fails.
            is_tty = sys.stderr.isatty()
            if is_tty:
                sys.stderr.write("Starting cage...")
                sys.stderr.flush()
            child = subprocess.Popen(up_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            up_out, up_err = child.communicate()
            if is_tty:
                sys.stderr.write("\r\033[K")  # carriage return + clear-to-end-of-line
                sys.stderr.flush()
            if child.returncode != 0:
                sys.stderr.write(up_out)
                sys.stderr.write(up_err)
                raise subprocess.CalledProcessError(child.returncode, up_cmd)

        # The cage is up. Re-own (from the host, never via in-cage sudo) any
        # root-owned parent dirs Docker created for home-nested mounts, so the
        # harness can write next to a single-file mount -- e.g. pi's session dir
        # beside a mounted models.json. See fix_mount_dir_ownership.
        fix_mount_dir_ownership(id_label, mount_parent_dirs or [], debug)

        child = subprocess.Popen(exec_cmd)
        child.wait()
        rc = child.returncode
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGHUP, previous_sighup)
        teardown_cage(id_label)
        discard_staged_dirs(discard_dirs or [])

    # A child killed by signal N reports -N; map it to the shell's 128+N.
    sys.exit(rc if rc >= 0 else 128 - rc)
