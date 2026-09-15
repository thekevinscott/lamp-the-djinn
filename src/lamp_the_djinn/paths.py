"""Host paths ltd derives: the embedded devcontainer dir and a run's workspace."""

from pathlib import Path


def get_embedded_devcontainer_dir() -> Path:
    """Get the path to embedded devcontainer files in the package."""
    return Path(__file__).parent / "devcontainer"


def get_workspace_dir(instance_id: str) -> Path:
    """Get instance-specific workspace directory for devcontainer files.

    Each instance gets its own directory to prevent race conditions when
    multiple lamp-the-djinn instances run with different configurations.
    """
    return Path.home() / ".cache" / "lamp-the-djinn" / f"workspace-{instance_id}"
