"""CLI entry points for lamp-the-djinn."""

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from . import harness as harness_mod

__all__ = ["main", "shell_remote"]


def get_embedded_devcontainer_dir() -> Path:
    """Get the path to embedded devcontainer files in the package."""
    return Path(__file__).parent / "devcontainer"


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


def get_workspace_dir(instance_id: str) -> Path:
    """Get instance-specific workspace directory for devcontainer files.

    Each instance gets its own directory to prevent race conditions when
    multiple lamp-the-djinn instances run with different configurations.
    """
    return Path.home() / ".cache" / "lamp-the-djinn" / f"workspace-{instance_id}"


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


def generate_ssh_config(runtime_dir: Path, ssh_key_name: str) -> Path:
    """Generate SSH config file for GitHub."""
    ssh_config = runtime_dir / "ssh_config"
    ssh_config.write_text(f"""Host github.com
  HostName github.com
  User git
  IdentityFile /home/node/.ssh/{ssh_key_name}
  IdentitiesOnly yes
""")
    # SSH requires strict permissions on config files
    ssh_config.chmod(0o644)
    return ssh_config


# Allowlist of names copied from the host ~/.claude into the strict-mode stage
# dir. Default-deny: anything NOT named here is never copied. In particular this
# excludes .credentials.json and any auth/token/credential-bearing file, so the
# untrusted agent never sees host credentials. `hooks` is included so the user's
# own hooks (e.g. the transcript-posting Stop hook) still run in strict mode --
# they execute against the disposable copy, so the agent can't persist changes
# to the host's hooks.
_CLAUDE_CONFIG_ALLOWLIST = ("settings.json", "CLAUDE.md", "commands", "agents", "skills", "hooks")


def stage_claude_config(home: Path, dest: Path) -> None:
    """Copy an allowlisted subset of host ``~/.claude`` config into ``dest``.

    Copies ONLY ``settings.json``, ``CLAUDE.md``, and the ``commands/``,
    ``agents/``, ``skills/`` dirs -- each only if it exists on the host. This is
    an allowlist (default-deny): unknown entries (including ``.credentials.json``
    or anything bearing ``credential``/``token``/``auth`` in its name) are never
    copied. The result is a disposable copy the cage can mount + freely mutate
    without touching the host or exposing host credentials.
    """
    src_root = home / ".claude"
    dest.mkdir(parents=True, exist_ok=True)

    for name in _CLAUDE_CONFIG_ALLOWLIST:
        src = src_root / name
        if not src.exists():
            continue
        target = dest / name
        if src.is_dir():
            # Follow symlinks (materialize skill/command content into the copy) but
            # skip dangling ones -- ~/.claude often has skills/commands symlinked to
            # other projects, some of which may be stale.
            shutil.copytree(src, target, dirs_exist_ok=True, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(src, target)


# The cage user's ids. The Dockerfile renames whatever user the Playwright base
# image left at 1000 to `node` (usermod -l / groupmod -n), so this is structural,
# not configuration.
CAGE_USER_UID = 1000
CAGE_USER_GID = 1000


def modify_config(
    config: dict,
    args: argparse.Namespace,
    runtime_dir: Path,
    devcontainer_dir: Path | None = None,
    project_dir: Path | None = None,
    proxy_url: str | None = None,
    model: str | None = None,
    proxy_api_key: str | None = None,
    runtime: str = "runc",
    trusted: bool = False,
    claude_stage_dir: Path | None = None,
) -> dict:
    """Modify devcontainer config with user-specific settings."""

    # If --build flag, replace image with build config
    if args.build and devcontainer_dir:
        config.pop("image", None)
        config["build"] = {"dockerfile": "Dockerfile", "context": "."}

    # Skip devcontainer's UID-remap step when it would rename the cage user to the
    # ids it already has. Left on (its default for a non-root remoteUser), the CLI
    # builds and exports an extra derived image on EVERY `up` -- and the cage is
    # torn down per run, so that cost is never amortized. Measured 2.4s -> 2.0s.
    #
    # BOTH ids must match: the remap sets uid and gid together, so opting out on a
    # partial match would leave bind-mounted files wrong-grouped, which is the
    # breakage the remap exists to prevent.
    if os.getuid() == CAGE_USER_UID and os.getgid() == CAGE_USER_GID:
        config["updateRemoteUserUID"] = False

    # Mount the project at its OWN host path (path identity), so absolute paths the
    # agent emits (code, configs, logs, commits) stay valid on the host -- no
    # /workspace remap that makes agents hallucinate /app-style paths.
    if project_dir:
        config["workspaceMount"] = f"source={project_dir},target={project_dir},type=bind,consistency=delegated"
        config["workspaceFolder"] = str(project_dir)

    # Trust-tiered ~/.claude config exposure.
    #
    # First, strip any pre-existing /home/node/.claude mount (the embedded
    # devcontainer.json ships a live rw bind) and the old claude-code-config
    # readonly-replace block, so we can append exactly the mount(s) the chosen
    # trust tier wants -- same pattern as the ssh/gpg filtering below.
    if "mounts" in config:
        config["mounts"] = [
            m for m in config["mounts"] if "/home/node/.claude" not in m and "claude-code-config" not in m
        ]

    config.setdefault("mounts", [])
    if trusted:
        # TRUSTED: live read-write bind of the host ~/.claude -- the agent's
        # config writes (settings, hooks, CLAUDE.md) land on the host directly.
        # This is the historical behavior, now opt-in only.
        config["mounts"].append("source=${localEnv:HOME}/.claude,target=/home/node/.claude,type=bind")
    else:
        # STRICT (default): mount a disposable COPY of the allowlisted config
        # (staged on the host by stage_claude_config) at /home/node/.claude. It
        # is rw inside the cage but the host ~/.claude is untouched, so the
        # agent's config writes are discarded on exit.
        #
        # DEFERRED: vet-on-exit selective apply of the agent's config changes.
        # Strict mode currently just discards them (safe); propagating approved
        # changes back to the host is a follow-up.
        if claude_stage_dir is not None:
            config["mounts"].append(f"source={claude_stage_dir},target=/home/node/.claude,type=bind")
        # Transcripts/session history are DATA, not config: write them back so
        # session continuity (`--continue`) and the transcript hook keep working.
        # These nested rw binds overlay the copied .claude with the live host
        # data dirs. (settings/hooks/CLAUDE.md remain the copied, discard-on-exit
        # part; only this transcript data is write-back safe.) Mount each only if
        # the host path exists, so a fresh install doesn't fail on a missing dir.
        home = Path.home()
        if (home / ".claude" / "projects").exists():
            config["mounts"].append(
                "source=${localEnv:HOME}/.claude/projects,target=/home/node/.claude/projects,type=bind"
            )
        if (home / ".claude" / "history.jsonl").exists():
            config["mounts"].append(
                "source=${localEnv:HOME}/.claude/history.jsonl,target=/home/node/.claude/history.jsonl,type=bind"
            )

    # Filter out existing SSH and GPG mounts
    if "mounts" in config:
        config["mounts"] = [m for m in config["mounts"] if ".ssh/" not in m and ".gnupg" not in m]

    # Add SSH mounts if key provided
    if args.ssh_key_file:
        ssh_key_path = Path(args.ssh_key_file).resolve()
        ssh_key_name = ssh_key_path.name
        ssh_config_path = generate_ssh_config(runtime_dir, ssh_key_name)

        config.setdefault("mounts", [])
        config["mounts"].append(f"source={ssh_key_path},target=/home/node/.ssh/{ssh_key_name},type=bind,readonly")
        config["mounts"].append(f"source={ssh_config_path},target=/home/node/.ssh/config,type=bind,readonly")

    # Add GPG mount if key ID provided
    if args.gpg_key_id:
        config.setdefault("mounts", [])
        config["mounts"].append("source=${localEnv:HOME}/.gnupg,target=/home/node/.gnupg,type=bind,readonly")

    # Machine-local firewall allowlist supplement. If the host has a
    # ~/.config/lamp-the-djinn/allowed-domains.txt, bind it read-only into the
    # cage where init-firewall.sh expects it. The firewall script resolves these
    # domains and adds them to the allowed-domains ipset (in addition to the
    # baked-in whitelist), letting a host opt extra domains through egress
    # without rebuilding the image.
    allowed_domains = Path.home() / ".config" / "lamp-the-djinn" / "allowed-domains.txt"
    if allowed_domains.exists():
        config.setdefault("mounts", [])
        config["mounts"].append(
            f"source={allowed_domains},target=/usr/local/share/ltd-allowed-domains.txt,type=bind,readonly"
        )

    # Per-run firewall allowlist supplement (--allow-domains-file / LTD_ALLOW_DOMAINS_FILE).
    # Host-supplied, this cage only. Distinct target from the machine-local file
    # above so both coexist; mounted READ-ONLY so the agent can read but not edit
    # it (writing fails EROFS) -- the firewall reads it once at startup, before the
    # agent runs, so the agent can never widen its own egress.
    run_domains_file = getattr(args, "allow_domains_file", None)
    if run_domains_file:
        run_domains_path = Path(run_domains_file).expanduser().resolve()
        config.setdefault("mounts", [])
        config["mounts"].append(
            f"source={run_domains_path},target=/usr/local/share/ltd-allowed-domains.run.txt,type=bind,readonly"
        )

    # Harness package cache mount -- TRUST-gated so npx/uvx don't re-download the
    # harness every run. Two tiers:
    #
    #   trusted   -> mount the host cache READ-WRITE and point npm/uv at it. The
    #                first run populates it; later runs reuse it (no re-download).
    #                The agent is trusted, so a writable host cache is acceptable.
    #   untrusted -> NO host cache mount and NO cache env. The cage uses its own
    #                writable in-container cache (ephemeral, re-downloads each run,
    #                but safe). We must NOT point npm/uv at a read-only host mount:
    #                npm writes to _cacache/tmp even while fetching, so a read-only
    #                cache fails hard with EROFS. (A read-only cooldown cache would
    #                need an overlay/copy to be writable-on-top; deferred.)
    use_cache_env = False
    if trusted:
        config.setdefault("mounts", [])
        config["mounts"].append(
            "source=${localEnv:HOME}/.cache/lamp-the-djinn/harness-cache,target=/home/node/.cache/ltd-harness,type=bind"
        )
        use_cache_env = True

    # WRITABLE credential-persistence mount. Harness sessions (e.g. an OAuth
    # token a harness writes after `login`) persist across runs via this volume.
    #
    # SECURITY PRINCIPLE: this mount is READ-WRITE and lives inside the cage, so
    # the untrusted agent can READ everything in it. Therefore persist ONLY
    # scoped/revocable credentials here. The model key never enters the cage --
    # it stays in the LiteLLM proxy on the host. The primary git identity stays
    # out too: push host-side, or supply a fine-grained, single-repo, revocable
    # PAT. See README "Credential persistence" for the full rationale.
    config.setdefault("mounts", [])
    config["mounts"].append(
        "source=${localEnv:HOME}/.cache/lamp-the-djinn/auth,target=/home/node/.config/ltd-auth,type=bind"
    )

    # Add docker run flags (ports, volumes, env vars) to runArgs
    config.setdefault("runArgs", [])

    # Per-cage memory cap (density default 2g). Strip any existing --memory=VALUE
    # or `--memory VALUE` pair from runArgs, then append our resolved cap.
    # --cpus / --pids-limit are left untouched.
    memory = getattr(args, "memory", None) or "2g"
    stripped_run_args: list[str] = []
    skip_next = False
    for run_arg in config["runArgs"]:
        if skip_next:
            skip_next = False
            continue
        if run_arg == "--memory":
            skip_next = True  # also drop the separate value token that follows
            continue
        if run_arg.startswith("--memory="):
            continue
        stripped_run_args.append(run_arg)
    config["runArgs"] = stripped_run_args
    config["runArgs"].append(f"--memory={memory}")

    # Quiet npm's notices/warnings in the cage (they bury the agent output);
    # loglevel=error still surfaces real failures (e.g. a failed npx fetch).
    config["runArgs"].extend(
        [
            "-e",
            "npm_config_update_notifier=false",
            "-e",
            "npm_config_fund=false",
            "-e",
            "npm_config_loglevel=error",
        ]
    )

    # Isolation seam: when a stronger OCI runtime than the stock runc was
    # resolved (e.g. gVisor's runsc or kata-runtime), tell Docker to use it.
    # For plain runc we add nothing, leaving default behavior untouched.
    if runtime != "runc":
        config["runArgs"].extend(["--runtime", runtime])

    if args.port:
        for port_mapping in args.port:
            # Support both HOST:CONTAINER and just PORT (same for both)
            if ":" not in port_mapping:
                port_mapping = f"{port_mapping}:{port_mapping}"
            config["runArgs"].extend(["-p", port_mapping])
    if args.volume:
        host_home = Path.home().resolve()
        for vol in args.volume:
            # An explicit `host:container` mapping is honored as-is.
            if ":" in vol:
                config["runArgs"].extend(["-v", vol])
                continue
            host_path = Path(vol).resolve()
            # A bare path UNDER the host HOME maps to the same relative location
            # under the cage user's HOME (`~/.pi` -> `/home/node/.pi`), so tools
            # that read HOME-relative config (pi's ~/.pi, npm's ~/.npmrc, ...) find
            # it -- the cage user is `node`, not the host user, so a path-identity
            # mount of a `$HOME` path lands where the cage never looks. This is the
            # same remap ltd already does by hand for ~/.claude, ~/.ssh, ~/.gnupg.
            # A path OUTSIDE HOME keeps path identity (`/mnt/x` -> `/mnt/x`) so the
            # absolute paths an agent emits stay valid on the host. NOTE: Docker
            # creates any absent parent dirs of a home-nested mount owned by ROOT;
            # ltd re-owns them to the cage user from the host once the cage is up
            # (see home_mount_parent_dirs / fix_mount_dir_ownership).
            if host_path == host_home or host_home in host_path.parents:
                target = Path("/home/node") / host_path.relative_to(host_home)
            else:
                target = host_path
            config["runArgs"].extend(["-v", f"{host_path}:{target}"])
    if args.env:
        for env_var in args.env:
            config["runArgs"].extend(["-e", env_var])

    # Point the in-container npm/uv caches at the mounted harness cache only when
    # it is mounted (trusted). Untrusted runs leave the cage's default writable
    # caches so npx/uvx fetch the harness fresh -- pointing npm/uv at a read-only
    # mount fails with EROFS (npm writes _cacache/tmp even while fetching).
    if use_cache_env:
        config["runArgs"].extend(["-e", "UV_CACHE_DIR=/home/node/.cache/ltd-harness/uv"])
        config["runArgs"].extend(["-e", "npm_config_cache=/home/node/.cache/ltd-harness/npm"])

    # Wire whatever command runs in the cage to the LiteLLM proxy on the host.
    if proxy_url:
        # Generic provider env (OPENAI_*/ANTHROPIC_*) for harnesses that read it.
        api_key = proxy_api_key or "lamp-the-djinn"
        prov_env = harness_mod.provider_env_all(proxy_url, model or "local", api_key)
        for key, value in prov_env.items():
            config["runArgs"].extend(["-e", f"{key}={value}"])

    # The container reaches the host (the LiteLLM proxy, or a host service a
    # harness config like pi's models.json points at) via the docker bridge
    # gateway. On Linux host.docker.internal is not automatic, so always map it
    # explicitly -- it must resolve regardless of whether ltd injects provider env.
    config["runArgs"].append("--add-host=host.docker.internal:host-gateway")

    # Build postStartCommand
    commands = ["sudo /usr/local/bin/init-firewall.sh"]

    if args.git_user_name:
        commands.append(f"git config --global user.name {shlex.quote(args.git_user_name)}")

    if args.git_user_email:
        commands.append(f"git config --global user.email {shlex.quote(args.git_user_email)}")

    if args.gpg_key_id:
        commands.append(f"git config --global user.signingkey {shlex.quote(args.gpg_key_id)}")
        commands.append("git config --global commit.gpgsign true")
        commands.append("git config --global gpg.program gpg")
        commands.append("gpg-connect-agent /bye >/dev/null 2>&1 || true")

    if args.gh_token:
        commands.append(f"echo {shlex.quote(args.gh_token)} | gh auth login --with-token")

    config["postStartCommand"] = " && ".join(commands)

    return config


def home_mount_parent_dirs(volumes: list[str] | None, host_home: Path) -> list[str]:
    """Cage-side dirs Docker auto-creates (owned by ROOT) for home-nested mounts.

    A bare `-v` under the host home is remapped to the same relative path under
    the cage home (`~/.pi/agent/models.json` -> `/home/node/.pi/agent/...`; see
    modify_config). Docker, mounting into a path whose parent dirs are absent
    from the image, creates that whole parent chain owned by ROOT -- so the cage
    user (`node`) cannot write siblings, and pi's first act,
    `mkdir ~/.pi/agent/sessions/...`, dies with EACCES. ltd re-owns these
    intermediate dirs to `node` from the host once the cage is up (see
    fix_mount_dir_ownership); it never touches the mount target itself (the bind
    point) nor the host file behind it.

    Returns the sorted, de-duplicated cage-side dirs to re-own -- the parents of
    each home-mapped mount target, from its containing dir up to (but excluding)
    the cage home. Empty when nothing nests below the cage home. Explicit
    `host:container` mounts are skipped: the user owns that layout.
    """
    cage_home = Path("/home/node")
    dirs: set[str] = set()
    for vol in volumes or []:
        if ":" in vol:
            continue
        host_path = Path(vol).resolve()
        if not (host_path == host_home or host_home in host_path.parents):
            continue
        target = cage_home / host_path.relative_to(host_home)
        parent = target.parent
        while parent != cage_home and cage_home in parent.parents:
            dirs.add(str(parent))
            parent = parent.parent
    return sorted(dirs)


def resolve_command(command: list[str], shell_cmd: str | None, safe_mode: bool) -> list[str]:
    """Decide what to run inside the cage.

    Precedence: explicit command > --shell CMD > default claude. The default
    preserves today's bare-`ltd` behavior: `claude --dangerously-skip-permissions`
    normally, or plain `claude` under --safe-mode (permission prompts on).
    `--shell CMD` is a convenience equal to `bash -c CMD`.

    A single REMAINDER token that contains whitespace is the user quoting the
    whole command as one string (`ltd 'npx -y pkg ...'`); we split it into argv so
    `devcontainer exec` does not receive one impossible binary name with spaces.
    Multi-token commands already arrived as argv and pass through verbatim.
    """
    if command:
        if len(command) == 1 and any(ch.isspace() for ch in command[0]):
            return shlex.split(command[0])
        return list(command)
    if shell_cmd:
        return ["bash", "-c", shell_cmd]
    if safe_mode:
        return ["claude"]
    return ["claude", "--dangerously-skip-permissions"]


def record_manifest(command: list[str]) -> None:
    """Record a harness package spec to the cache-freshness manifest.

    If the command is `npx <pkg>` / `npm ... <pkg>` or `uvx <pkg>` /
    `uv tool ... <pkg>`, append the first obvious (non-flag) package token to
    ``~/.cache/lamp-the-djinn/harness-manifest.txt`` (deduped). The trusted
    nightly refresh (scripts/refresh-harness-cache.sh) reads this file to warm
    the read-only harness cache with packages users actually invoke.

    Conservative by design: records only the first non-flag arg after the
    package-runner token, and only for the runners above. Anything else is a
    no-op.
    """
    if not command:
        return

    runner = command[0]
    rest = command[1:]

    if runner in ("npx", "uvx"):
        # `npx <pkg>` / `uvx <pkg>`: first non-flag arg is the package spec.
        pkg = _first_non_flag(rest)
    elif runner == "npm" and rest and rest[0] in ("install", "i", "exec", "x"):
        # `npm install/exec <pkg>`: spec follows the subcommand.
        pkg = _first_non_flag(rest[1:])
    elif runner == "uv" and rest and rest[0] == "tool":
        # `uv tool install/run <pkg>`: spec follows `tool <subcommand>`.
        pkg = _first_non_flag(rest[2:]) if len(rest) > 1 else None
    else:
        return

    if not pkg:
        return

    manifest = Path.home() / ".cache" / "lamp-the-djinn" / "harness-manifest.txt"
    manifest.parent.mkdir(parents=True, exist_ok=True)

    existing = manifest.read_text().splitlines() if manifest.exists() else []
    if pkg in existing:
        return

    with manifest.open("a") as f:
        f.write(f"{pkg}\n")


def _first_non_flag(args: list[str]) -> str | None:
    """Return the first argument that does not start with '-', or None."""
    for a in args:
        if not a.startswith("-"):
            return a
    return None


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="Run any coding agent in a sandboxed devcontainer. "
        "The command after ltd's own options is run inside the cage: "
        "ltd [ltd-opts] <command...>",
        epilog=(
            "Examples:\n"
            '  ltd claude -p "fix the failing test"\n'
            "  ltd npx @anthropic/claude\n"
            "  ltd --model glm-5.2 aider\n"
            "  ltd                       # bare: runs claude --dangerously-skip-permissions\n"
            "\n"
            "Everything after ltd's options is the command to run in the cage; the "
            "command's own flags (e.g. -p) are passed through untouched."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ssh-key-file", help="Path to SSH private key")
    parser.add_argument("--git-user-name", help="Git user.name")
    parser.add_argument("--git-user-email", help="Git user.email")
    parser.add_argument("--gh-token", help="GitHub token")
    parser.add_argument("--gpg-key-id", help="GPG key ID for signing")
    parser.add_argument(
        "--build", action="store_true", help="Build from local Dockerfile instead of using pre-built image"
    )
    parser.add_argument(
        "--model", default=None, help="Model name passed to the harness via the LiteLLM proxy (default: local)"
    )
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="LiteLLM proxy base URL. If set, the harness is wired to it. "
        "Defaults to http://host.docker.internal:4000/v1 when a proxy is in use",
    )
    parser.add_argument(
        "--runtime",
        default=None,
        help="OCI isolation runtime for Docker (the isolation seam): "
        "'auto' (default) uses the lightest sane runtime, runc. "
        "gVisor/Kata are opt-in only -- pass a concrete name like 'runsc' or "
        "'kata-runtime' (runsc breaks the egress firewall; Kata is full-VM). "
        "Env: LTD_RUNTIME",
    )
    parser.add_argument(
        "--trusted",
        action="store_true",
        help="Expose the host ~/.claude config READ-WRITE (live bind) instead of a "
        "disposable copy. Governs config exposure only -- not runtime or firewall. "
        "Default (strict) mounts an allowlisted copy so the agent never sees host "
        "credentials and its config writes are discarded on exit. Env: LTD_TRUSTED",
    )
    parser.add_argument(
        "--memory",
        default=None,
        metavar="LIMIT",
        help="Per-cage memory cap passed to docker (default: 2g). Env: LTD_MEMORY",
    )
    parser.add_argument("--shell", metavar="CMD", help="Run a shell command instead of the harness (for testing)")
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="Run the harness with permission prompts enabled (more interruptions, extra safety)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show all build/firewall/devcontainer output (default: only the agent's output). Env: LTD_DEBUG",
    )
    # Docker run flags - passed directly to runArgs
    parser.add_argument(
        "-p",
        "--port",
        action="append",
        metavar="HOST:CONTAINER",
        help="Map a port from host to container (can be specified multiple times)",
    )
    parser.add_argument(
        "-v",
        "--volume",
        action="append",
        metavar="DIR",
        help="Mount a host dir into the cage. A path under your home maps to the "
        "cage user's home (~/.pi -> the cage's ~/.pi); a path elsewhere keeps its "
        "OWN path (identity), e.g. -v /mnt/bertha/app; or HOST:CONTAINER for an "
        "explicit target. Repeatable.",
    )
    parser.add_argument(
        "-e",
        "--env",
        action="append",
        metavar="VAR=VALUE",
        help="Set environment variable (can be specified multiple times)",
    )
    parser.add_argument(
        "--allow-domains-file",
        metavar="PATH",
        help="Open extra egress domains for THIS cage only: a file with one domain "
        "per line, mounted read-only so the agent cannot widen its own egress. "
        "Env: LTD_ALLOW_DOMAINS_FILE",
    )
    # The command to run inside the cage. REMAINDER captures everything after
    # ltd's own options verbatim, so the command's own flags (-p, -v, ...) are
    # NOT stolen by ltd's -p/-v/-e. Empty => default claude (see resolve_command).
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="command...",
        help='Command to run in the cage, e.g. `claude -p "hi"` or `npx @anthropic/claude`. '
        "Default: claude --dangerously-skip-permissions",
    )
    return parser


def apply_env_defaults(args: argparse.Namespace) -> None:
    """Apply environment variable defaults to args."""
    args.ssh_key_file = args.ssh_key_file or os.environ.get("LTD_SSH_KEY")
    args.git_user_name = args.git_user_name or os.environ.get("LTD_GIT_USER_NAME")
    args.git_user_email = args.git_user_email or os.environ.get("LTD_GIT_USER_EMAIL")
    args.gh_token = args.gh_token or os.environ.get("LTD_GH_TOKEN")
    args.gpg_key_id = args.gpg_key_id or os.environ.get("LTD_GPG_KEY_ID")
    args.model = args.model or os.environ.get("LTD_MODEL") or "local"
    args.proxy_url = args.proxy_url or os.environ.get("LTD_PROXY_URL")
    # Proxy auth: LiteLLM master key. Defaults to the project's literal placeholder.
    args.proxy_api_key = os.environ.get("LTD_PROXY_API_KEY", "lamp-the-djinn")
    # Isolation runtime preference. "auto" resolves to the lightest sane runtime
    # (runc); gVisor/Kata are opt-in via --runtime / LTD_RUNTIME only.
    args.runtime = args.runtime or os.environ.get("LTD_RUNTIME") or "auto"
    args.debug = args.debug or bool(os.environ.get("LTD_DEBUG"))
    # Trust tier for ~/.claude CONFIG exposure (default strict). Opt-in only.
    args.trusted = args.trusted or bool(os.environ.get("LTD_TRUSTED"))
    # Per-cage memory cap. Falls back to the 2g default inside modify_config.
    args.memory = args.memory or os.environ.get("LTD_MEMORY")
    # Per-run egress allowlist file. Host-only (the agent can't set this), mounted
    # read-only into the single cage this run launches.
    args.allow_domains_file = args.allow_domains_file or os.environ.get("LTD_ALLOW_DOMAINS_FILE")


def teardown_cage(id_label: str) -> None:
    """Force-remove the cage container(s) carrying this instance's label.

    `devcontainer up` starts a PERSISTENT container; the agent runs inside it and
    exits, but the container keeps running. Each ltd run uses a fresh instance id,
    so the cage is never reused -- leaving it up just orphans one container per
    run. There is no `devcontainer down` for a single instance, so we resolve the
    labelled container id(s) and `docker rm -f` them. Best-effort and quiet: a
    teardown failure must not mask the command's own exit code.
    """
    found = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={id_label}"],
        capture_output=True,
        text=True,
    )
    ids = found.stdout.split()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, text=True)


def fix_mount_dir_ownership(id_label: str, dirs: list[str], debug: bool = False) -> None:
    """Re-own to the cage user the root-owned parent dirs Docker created for
    home-nested bind mounts (see home_mount_parent_dirs).

    Done from the HOST via the Docker daemon -- ltd already has Docker access --
    NOT from inside the cage. That is the security-load-bearing choice: it keeps
    the untrusted agent with NO standing root primitive. Putting a `sudo chown`
    in the cage's postStartCommand instead would force `chown` onto the cage's
    passwordless-sudo allowlist (today only init-firewall.sh / ipset), handing
    the agent a general root-owns-anything escalation. Non-recursive on purpose:
    it touches only the dirs themselves, never the bind-mounted file (chowning
    that would change the HOST file's owner through the shared inode).

    Best-effort: a teardown/run must not be aborted by a chown hiccup; surface
    failures only in debug.
    """
    if not dirs:
        return
    found = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={id_label}"],
        capture_output=True,
        text=True,
    )
    ids = found.stdout.split()
    if not ids:
        return
    result = subprocess.run(
        ["docker", "exec", "--user", "root", ids[0], "chown", "node:node", *dirs],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and debug:
        print(f"Could not re-own mount parent dirs {dirs}: {result.stderr.strip()}", file=sys.stderr)


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

    # A child killed by signal N reports -N; map it to the shell's 128+N.
    sys.exit(rc if rc >= 0 else 128 - rc)


IMAGE_NAME = "ghcr.io/thekevinbot/lamp-the-djinn:latest"


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


def print_container_info(image_name: str) -> None:
    """Print container build information on startup."""
    info = get_container_info(image_name)

    source_display = "GitHub Container Registry (ghcr.io)" if info["source"] == "ghcr.io" else "Local build"
    build_time_display = info["build_time"] if info["build_time"] != "unknown" else "Unknown"

    print(f"Container image: {image_name}")
    print(f"  Built: {build_time_display}")
    print(f"  Source: {source_display}")
    print()


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


def pull_docker_image_if_needed(debug: bool = False) -> None:
    """Pull the Docker image if not already present."""
    result = subprocess.run(["docker", "image", "inspect", IMAGE_NAME], capture_output=True)
    if result.returncode != 0:
        if debug:
            print("Pulling Docker image...")
        # Capture so a pull failure (e.g. image not published) stays quiet; the
        # caller catches CalledProcessError and falls back to a local build.
        subprocess.run(["docker", "pull", IMAGE_NAME], check=True, capture_output=True, text=True)


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
