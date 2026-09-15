"""The admin frame as plain text. Pure: no terminal, no escape codes."""

TITLE = "lamp-the-djinn admin"
HINT = "q  quit"
BLURB = "Nothing to administer yet. This screen proves the TUI plumbing works."


def render_admin_screen(version: str, *, cols: int = 80, rows: int = 24) -> str:
    """The admin frame as plain text: a centered box. No escape codes."""
    body = [TITLE, "", f"version {version}", "", BLURB, "", HINT]
    inner = min(max(len(line) for line in body) + 4, max(cols - 2, 4))
    box = [
        "┌" + "─" * inner + "┐",
        *("│" + line[:inner].center(inner) + "│" for line in body),
        "└" + "─" * inner + "┘",
    ]
    left = " " * max((cols - inner - 2) // 2, 0)
    top = [""] * max((rows - len(box)) // 2, 0)
    return "\n".join(top + [left + line for line in box])
