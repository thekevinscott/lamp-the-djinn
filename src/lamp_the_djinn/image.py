"""The cage image, and pulling it when the host doesn't have it yet."""

import subprocess

IMAGE_NAME = "ghcr.io/thekevinscott/lamp-the-djinn:latest"


def pull_docker_image_if_needed(debug: bool = False) -> None:
    """Pull the Docker image if not already present."""
    result = subprocess.run(["docker", "image", "inspect", IMAGE_NAME], capture_output=True)
    if result.returncode != 0:
        if debug:
            print("Pulling Docker image...")
        # Capture so a pull failure (e.g. image not published) stays quiet; the
        # caller catches CalledProcessError and falls back to a local build.
        subprocess.run(["docker", "pull", IMAGE_NAME], check=True, capture_output=True, text=True)
