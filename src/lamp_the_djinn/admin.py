"""The `ltd admin` screen: a host-side TUI, drawn with stdlib ANSI.

No toolkit, no runtime dependency. ltd ships zero dependencies and `uvx
lamp-the-djinn` cold start is user-visible; a static screen does not justify
paying for `rich` or `textual`. When the admin surface grows real widgets, that
is the moment to adopt one deliberately (see ARCHITECTURE.md).

The frame itself is pure (``admin_screen.render_admin_screen``); this module owns
only the terminal lifecycle -- alternate screen, cbreak key read, unconditional
restore.
"""

import os
import shutil
import sys
import termios
import tty
from typing import TextIO

from . import __version__
from .admin_screen import render_admin_screen

__all__ = ["is_admin_command", "run_admin"]

# q, Esc, Ctrl-C, Ctrl-D. Ctrl-C normally arrives as SIGINT (cbreak keeps ISIG),
# but a terminal with ISIG off delivers the raw byte, so honor both.
QUIT_KEYS = frozenset("q\x1b\x03\x04")

ENTER_ALT_SCREEN = "\x1b[?1049h\x1b[H"
LEAVE_ALT_SCREEN = "\x1b[?1049l"


def is_admin_command(command: list[str]) -> bool:
    """True when the passthrough command is exactly the reserved ``admin`` token.

    The reservation is deliberately narrow. Everything after ltd's own options is
    ``argparse.REMAINDER``, so a cage program named ``admin`` is indistinguishable
    from the subcommand. Reserving only the BARE form keeps `ltd admin --status`
    (and every other argument form) a passthrough; `ltd --shell admin` reaches a
    bare cage ``admin``.
    """
    return command == ["admin"]


def run_admin(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Draw the admin screen and block until the user quits. Returns an exit code.

    Piped or redirected (`ltd admin | cat`), there is no terminal to take over and
    no key to wait for, so the frame is printed once and ltd exits.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    if not (stdin.isatty() and stdout.isatty()):
        stdout.write(render_admin_screen(__version__) + "\n")
        stdout.flush()
        return 0

    cols, rows = shutil.get_terminal_size((80, 24))
    frame = render_admin_screen(__version__, cols=cols, rows=rows)

    fd = stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        stdout.write(ENTER_ALT_SCREEN + frame)
        stdout.flush()
        while True:
            key = os.read(fd, 1).decode("utf-8", "ignore")
            if key == "" or key in QUIT_KEYS:
                break
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        stdout.write(LEAVE_ALT_SCREEN)
        stdout.flush()
    return 0
