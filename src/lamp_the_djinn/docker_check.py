"""Fail fast, and legibly, when Docker is not reachable."""

import subprocess
import sys


def check_docker_accessible() -> None:
    """Check Docker is installed, running and accessible. Exit with error if not."""
    try:
        failed = subprocess.run(["docker", "info"], capture_output=True, text=True).returncode != 0
        problem = "not running or not accessible"
    except FileNotFoundError:
        failed = True
        problem = "not installed (no docker on PATH)"
    if failed:
        print(
            "\n"
            "╔════════════════════════════════════════════════════════════════╗\n"
            f"║  ERROR: Docker is {problem:<44}║\n"
            "╠════════════════════════════════════════════════════════════════╣\n"
            "║  lamp-the-djinn requires Docker to run.                       ║\n"
            "║                                                                ║\n"
            "║  Please ensure:                                               ║\n"
            "║    1. Docker is installed                                     ║\n"
            "║    2. Docker daemon is running                                ║\n"
            "║    3. You have permission to access Docker                    ║\n"
            "║       (try: sudo usermod -aG docker $USER)                    ║\n"
            "╚════════════════════════════════════════════════════════════════╝\n",
            file=sys.stderr,
        )
        sys.exit(1)
