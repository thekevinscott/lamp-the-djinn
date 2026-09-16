"""Unit tests for the pure admin frame."""

import pytest

from .admin_screen import HINT, TITLE, render_admin_screen

pytestmark = pytest.mark.unit


def describe_rendering_the_admin_screen():
    def it_shows_the_title_the_version_and_the_quit_hint():
        screen = render_admin_screen("1.2.3")

        assert TITLE in screen
        assert "version 1.2.3" in screen
        assert HINT in screen

    def it_carries_no_escape_codes():
        """Escape sequences belong to run_admin; the frame is plain text."""
        assert "\x1b" not in render_admin_screen("1.2.3")

    def it_fits_inside_the_terminal_width():
        screen = render_admin_screen("1.2.3", cols=40, rows=24)

        assert max(len(line) for line in screen.splitlines()) <= 40

    def it_centers_the_box_in_the_viewport():
        lines = render_admin_screen("1.2.3", cols=100, rows=40).splitlines()
        box = [line for line in lines if line.strip()]

        assert lines[0] == "", "expected blank padding above the box"
        assert box[0].startswith(" "), "expected blank padding left of the box"
