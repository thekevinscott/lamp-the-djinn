"""Turn the embedded devcontainer.json into this run's cage configuration."""

import argparse
import os
import shlex
from pathlib import Path

from . import harness as harness_mod
from .ssh_config import generate_ssh_config

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
    gnupg_stage_dir: Path | None = None,
) -> dict:
    """Modify devcontainer config with user-specific settings."""

    # If --build flag, replace image with build config
    if args.build and devcontainer_dir:
        config.pop("image", None)
        config["build"] = {"dockerfile": "Dockerfile", "context": "."}

    # The remap sets uid and gid together, so a partial match must NOT opt out --
    # that leaves bind-mounted files wrong-grouped.
    if os.getuid() == CAGE_USER_UID and os.getgid() == CAGE_USER_GID:
        config["updateRemoteUserUID"] = False

    # Mount the project at its OWN host path (path identity), so absolute paths the
    # agent emits (code, configs, logs, commits) stay valid on the host -- no
    # /workspace remap that makes agents hallucinate /app-style paths.
    if project_dir:
        config["workspaceMount"] = f"source={project_dir},target={project_dir},type=bind,consistency=delegated"
        config["workspaceFolder"] = str(project_dir)

    # The embedded devcontainer.json ships a live rw bind; strip it before
    # appending whatever the trust tier wants.
    if "mounts" in config:
        config["mounts"] = [
            m for m in config["mounts"] if "/home/node/.claude" not in m and "claude-code-config" not in m
        ]

    config.setdefault("mounts", [])
    if trusted:
        config["mounts"].append("source=${localEnv:HOME}/.claude,target=/home/node/.claude,type=bind")
    else:
        if claude_stage_dir is not None:
            config["mounts"].append(f"source={claude_stage_dir},target=/home/node/.claude,type=bind")
        # Transcripts are data, not config: write them back so `--continue` keeps
        # working. Only this data is write-back safe.
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

    # Must be the writable staged copy, never the host ~/.gnupg: gpg-agent writes
    # its socket inside GNUPGHOME, so a read-only bind cannot start it at all.
    if args.gpg_key_id and gnupg_stage_dir is not None:
        config.setdefault("mounts", [])
        config["mounts"].append(f"source={gnupg_stage_dir},target=/home/node/.gnupg,type=bind")

    # Machine-local firewall allowlist supplement, at the path init-firewall.sh
    # expects.
    allowed_domains = Path.home() / ".config" / "lamp-the-djinn" / "allowed-domains.txt"
    if allowed_domains.exists():
        config.setdefault("mounts", [])
        config["mounts"].append(
            f"source={allowed_domains},target=/usr/local/share/ltd-allowed-domains.txt,type=bind,readonly"
        )

    # Read-only, and a distinct target from the machine-local file so both
    # coexist. Writable would let the agent widen its own egress.
    run_domains_file = getattr(args, "allow_domains_file", None)
    if run_domains_file:
        run_domains_path = Path(run_domains_file).expanduser().resolve()
        config.setdefault("mounts", [])
        config["mounts"].append(
            f"source={run_domains_path},target=/usr/local/share/ltd-allowed-domains.run.txt,type=bind,readonly"
        )

    # Trusted only, and read-write. A read-only cache is not a safe middle ground:
    # npm writes _cacache/tmp even while fetching, so it fails EROFS.
    use_cache_env = False
    if trusted:
        config.setdefault("mounts", [])
        config["mounts"].append(
            "source=${localEnv:HOME}/.cache/lamp-the-djinn/harness-cache,target=/home/node/.cache/ltd-harness,type=bind"
        )
        use_cache_env = True

    # The untrusted agent can read everything in here, so only scoped, revocable
    # credentials belong in it. See README "Credential persistence".
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
            # A HOME-relative path is remapped under the cage user's HOME, because
            # the cage user is `node` -- path identity would land where nothing
            # looks. Outside HOME, keep path identity so the absolute paths an
            # agent emits stay valid on the host.
            if host_path == host_home or host_home in host_path.parents:
                target = Path("/home/node") / host_path.relative_to(host_home)
            else:
                target = host_path
            config["runArgs"].extend(["-v", f"{host_path}:{target}"])
    if args.env:
        for env_var in args.env:
            config["runArgs"].extend(["-e", env_var])

    # Only when the cache is actually mounted. Pointing npm/uv at a missing or
    # read-only path fails EROFS.
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

    # Not automatic on Linux, and must resolve whether or not ltd injects
    # provider env.
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
