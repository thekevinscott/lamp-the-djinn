"""Read build provenance off the cage image's OCI labels."""

import subprocess


def get_container_info(image_name: str) -> dict:
    """Get container build info from Docker image labels.

    Returns dict with 'build_time' and 'source' keys.
    """
    result = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            image_name,
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.created"}}|'
            '{{index .Config.Labels "org.opencontainers.image.source.type"}}',
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"build_time": "unknown", "source": "unknown"}

    parts = result.stdout.strip().split("|")
    build_time = parts[0] if parts[0] else "unknown"
    source = parts[1] if len(parts) > 1 and parts[1] else "local"

    return {"build_time": build_time, "source": source}
