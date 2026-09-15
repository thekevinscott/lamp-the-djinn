"""Record harness package specs to the cache-freshness manifest."""

from pathlib import Path

from .first_non_flag import first_non_flag


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
        pkg = first_non_flag(rest)
    elif runner == "npm" and rest and rest[0] in ("install", "i", "exec", "x"):
        # `npm install/exec <pkg>`: spec follows the subcommand.
        pkg = first_non_flag(rest[1:])
    elif runner == "uv" and rest and rest[0] == "tool":
        # `uv tool install/run <pkg>`: spec follows `tool <subcommand>`.
        pkg = first_non_flag(rest[2:]) if len(rest) > 1 else None
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
