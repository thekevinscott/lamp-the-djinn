"""Scan an argv tail for its first non-flag token."""


def first_non_flag(args: list[str]) -> str | None:
    """Return the first argument that does not start with '-', or None."""
    for a in args:
        if not a.startswith("-"):
            return a
    return None
