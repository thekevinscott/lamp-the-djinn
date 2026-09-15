"""Stage a disposable, allowlisted copy of the host ``~/.claude`` for strict mode."""

import shutil
from pathlib import Path

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
