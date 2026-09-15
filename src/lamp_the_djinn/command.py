"""Decide what argv runs inside the cage."""

import shlex


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
