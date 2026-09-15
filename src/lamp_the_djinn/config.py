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
