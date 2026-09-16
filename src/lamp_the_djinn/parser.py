"""ltd's own option surface: everything before the in-cage command."""

import argparse


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
            "  ltd admin                 # host-side admin screen (no cage)\n"
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
