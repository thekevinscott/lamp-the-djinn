"""Fail fast, and legibly, when Docker is not reachable."""

import subprocess
import sys


def check_docker_accessible() -> None:
    """Check if Docker is running and accessible. Exit with error if not."""
    result = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if result.returncode != 0:
        print(
            "\n"
            "╔════════════════════════════════════════════════════════════════╗\n"
            "║  ERROR: Docker is not running or not accessible               ║\n"
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
