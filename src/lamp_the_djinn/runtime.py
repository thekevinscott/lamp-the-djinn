"""Resolve which OCI runtime Docker should use for the cage."""

import json
import subprocess
import sys


def detect_runtime(preferred: str) -> str:
    """Resolve which OCI runtime to hand to Docker (the "isolation seam").

    Queries Docker for its registered runtimes and reconciles the user's
    preference against what is actually installed.

    - preferred == "auto" (the default): the lightest sane runtime, "runc".
      gVisor/Kata are NOT auto-selected. gVisor's "runsc" breaks the cage's
      ipset egress firewall (the primary containment), and Kata adds full-VM
      overhead; opt into either explicitly via --runtime when you specifically
      want kernel-level isolation and accept the tradeoff.
    - preferred is a concrete name (e.g. "runsc", "kata-runtime", "runc"):
      use it if Docker reports it, otherwise warn on stderr and fall back to
      "runc" so the run still proceeds.

    Robust to any docker failure (missing binary, daemon down, malformed
    output): always returns a usable runtime ("runc").
    """
    # The default path needs no Docker query: the lightest sane runtime is
    # always runc, which every Docker host has. Only a concrete non-runc
    # request (runsc/kata) is validated against what Docker actually registers.
    if preferred in ("auto", "runc"):
        return "runc"

    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            available: list[str] = []
        else:
            runtimes = json.loads(result.stdout.strip() or "{}")
            available = list(runtimes.keys()) if isinstance(runtimes, dict) else []
    except (OSError, ValueError):
        available = []

    if preferred in available:
        return preferred

    print(
        f"Warning: requested isolation runtime '{preferred}' is not registered with Docker; falling back to 'runc'.",
        file=sys.stderr,
    )
    return "runc"
