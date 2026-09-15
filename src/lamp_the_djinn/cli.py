"""CLI entry points for lamp-the-djinn.

This module is the composition root: it wires the pieces together and holds no
decision of its own. Each collaborator lives in its own module (one non-trivial
function per file, per `unit one-function-per-file`).
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from .admin import is_admin_command, run_admin
from .claude_config import stage_claude_config
from .config import modify_config
from .container_banner import print_container_info
from .devcontainer_files import extract_devcontainer_files
from .devcontainer_run import run_devcontainer
from .docker_check import check_docker_accessible
from .env_defaults import apply_env_defaults
from .home_mounts import home_mount_parent_dirs
from .image import IMAGE_NAME, pull_docker_image_if_needed
from .manifest import record_manifest
from .parser import create_parser
from .runtime import detect_runtime

__all__ = ["main", "shell_remote"]


def main() -> None:
    """
    Main entry point - runs a command (the harness) in a sandboxed devcontainer.

    The command is whatever the user types after ltd's own options:
    `ltd [ltd-opts] <command...>`. With no command, defaults to claude.

    Uses embedded devcontainer files from the package.
    With --build, builds from Dockerfile. Without, uses pre-built image.
    """
    parser = create_parser()
    args = parser.parse_args()

    # `ltd admin` is host-side: no cage, no Docker probe. Dispatch before any of
    # the cage setup below runs.
    if is_admin_command(args.command):
        sys.exit(run_admin())

    # Detect whether the user explicitly engaged the proxy feature (via the
    # --model/--proxy-url flags or the LTD_MODEL/LTD_PROXY_URL env) BEFORE
    # apply_env_defaults coalesces everything to defaults. Merely giving a command
    # does NOT engage the proxy: a bare `ltd npx pi ...` injects no provider env
    # and leaves the proxy URL unset, so the harness uses its own config (e.g. the
    # user's mounted ~/.pi). Provider env is injected only on explicit opt-in.
    proxy_engaged = any(
        [
            args.proxy_url is not None,
            args.model is not None,
            os.environ.get("LTD_PROXY_URL"),
            os.environ.get("LTD_MODEL"),
        ]
    )

    apply_env_defaults(args)

    # Record any package-runner command (npx/uvx/etc.) to the cache-freshness
    # manifest so the trusted nightly refresh can warm it ahead of time.
    record_manifest(args.command)

    # Determine the proxy URL. When the proxy is engaged but no explicit URL was
    # given, default to the host bridge gateway (reached via --add-host below).
    proxy_url = args.proxy_url
    if proxy_url is None and proxy_engaged:
        proxy_url = "http://host.docker.internal:4000/v1"

    if args.ssh_key_file and not Path(args.ssh_key_file).exists():
        print(f"Error: SSH key not found at {args.ssh_key_file}", file=sys.stderr)
        sys.exit(1)

    # Check Docker is running before proceeding
    check_docker_accessible()

    # Resolve the isolation runtime against what Docker actually has registered.
    # Default ("auto") yields runc (no --runtime flag added); a stronger runtime
    # is used only when explicitly requested and registered with Docker.
    runtime = detect_runtime(args.runtime)
    if args.debug:
        print(f"Isolation runtime: {runtime}")

    # Pull the prebuilt image if not building locally. If it can't be pulled
    # (not published to the registry yet, or no access), fall back to building
    # locally so the run still works instead of crashing.
    if not args.build:
        try:
            pull_docker_image_if_needed(args.debug)
            if args.debug:
                print_container_info(IMAGE_NAME)
        except subprocess.CalledProcessError:
            if args.debug:
                print(f"Could not pull {IMAGE_NAME}; building locally instead.", file=sys.stderr)
            args.build = True
    elif args.debug:
        print("Container image: Local build (--build flag)")

    # Capture current working directory (the project to mount)
    project_dir = Path.cwd().resolve()

    # Generate unique instance ID early - used for both cache dir and container ID
    instance_id = uuid.uuid4().hex[:12]

    # Extract embedded devcontainer files to instance-specific cache directory
    # This prevents race conditions when multiple instances run concurrently
    cache_dir = extract_devcontainer_files(instance_id)
    devcontainer_dir = cache_dir / ".devcontainer"
    source_config = devcontainer_dir / "devcontainer.json"

    # Setup runtime directory for SSH config etc (shared, not instance-specific)
    runtime_dir = Path.home() / ".claude" / "lamp-the-djinn-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the writable credential-persistence dir exists on the host before
    # we bind-mount it into the cage. Contents are readable by the untrusted
    # agent, so only scoped/revocable credentials belong here (see README).
    auth_dir = Path.home() / ".cache" / "lamp-the-djinn" / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the harness package cache dir exists on the host so the writable
    # (trusted) bind mount has a source. First run populates it; later runs reuse
    # it so npx/uvx don't re-download the harness every time (see modify_config).
    harness_cache_dir = Path.home() / ".cache" / "lamp-the-djinn" / "harness-cache"
    harness_cache_dir.mkdir(parents=True, exist_ok=True)

    # Strict mode (default): stage a disposable, allowlisted copy of the host
    # ~/.claude config into this instance's cache dir and mount THAT instead of
    # the live host config. Trusted mode skips this and binds the host directly.
    claude_stage_dir: Path | None = None
    if not args.trusted:
        claude_stage_dir = cache_dir / "claude-config-stage"
        stage_claude_config(Path.home(), claude_stage_dir)

    # Load and modify config
    config = json.loads(source_config.read_text())
    config = modify_config(
        config,
        args,
        runtime_dir,
        devcontainer_dir,
        project_dir,
        proxy_url=proxy_url,
        model=args.model,
        proxy_api_key=args.proxy_api_key,
        runtime=runtime,
        trusted=args.trusted,
        claude_stage_dir=claude_stage_dir,
    )

    # Write modified config back to the temp devcontainer dir
    runtime_config = devcontainer_dir / "devcontainer.json"
    runtime_config.write_text(json.dumps(config, indent=2))

    # Dirs Docker will create as ROOT for any home-nested `-v` mount; ltd re-owns
    # them to the cage user once the cage is up so a single-file mount stays
    # writable (e.g. pi's session dir beside models.json).
    mount_parent_dirs = home_mount_parent_dirs(args.volume, Path.home().resolve())

    run_devcontainer(
        runtime_config,
        cache_dir,
        project_dir,
        args.command,
        args.shell,
        args.safe_mode,
        instance_id,
        mount_parent_dirs=mount_parent_dirs,
        debug=args.debug,
    )


def shell_remote() -> None:
    """Alias for main() - for lamp-the-djinn-remote entry point."""
    main()
