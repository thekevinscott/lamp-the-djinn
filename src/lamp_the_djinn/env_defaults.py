"""Fill unset CLI options from the LTD_* environment."""

import argparse
import os


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
