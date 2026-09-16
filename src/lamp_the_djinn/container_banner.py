"""Print the cage image's provenance banner at startup."""

from .container_info import get_container_info


def print_container_info(image_name: str) -> None:
    """Print container build information on startup."""
    info = get_container_info(image_name)

    source_display = "GitHub Container Registry (ghcr.io)" if info["source"] == "ghcr.io" else "Local build"
    build_time_display = info["build_time"] if info["build_time"] != "unknown" else "Unknown"

    print(f"Container image: {image_name}")
    print(f"  Built: {build_time_display}")
    print(f"  Source: {source_display}")
    print()
