"""Materialize the package's embedded devcontainer files for a run."""

import shutil
from pathlib import Path

from .paths import get_embedded_devcontainer_dir, get_workspace_dir


def extract_devcontainer_files(instance_id: str) -> Path:
    """Extract embedded devcontainer files to an instance-specific cache directory."""
    workspace_dir = get_workspace_dir(instance_id)
    devcontainer_dir = workspace_dir / ".devcontainer"
    devcontainer_dir.mkdir(parents=True, exist_ok=True)

    pkg_dir = get_embedded_devcontainer_dir()
    for f in pkg_dir.iterdir():
        if f.is_file() and f.name != "__init__.py" and not f.name.endswith(".pyc"):
            shutil.copy2(f, devcontainer_dir / f.name)

    return workspace_dir
