"""
Unit tests for stage_claude_config: the strict-mode allowlist copy of the host
~/.claude -- config in, credentials never.

Style is pytest-describe (describe_/it_ blocks).
"""

from pathlib import Path

import pytest

from lamp_the_djinn.claude_config import stage_claude_config

pytestmark = pytest.mark.unit


def _make_claude_home(home: Path) -> Path:
    """Populate a fake ~/.claude with allowlisted config + planted secrets."""
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "settings.json").write_text('{"theme": "dark"}')
    (claude / "CLAUDE.md").write_text("# project memory")
    (claude / "commands").mkdir()
    (claude / "commands" / "foo.md").write_text("do foo")
    (claude / "agents").mkdir()
    (claude / "skills").mkdir()
    # Secrets that must NEVER be copied.
    (claude / ".credentials.json").write_text('{"oauth": "SECRET"}')
    (claude / "auth-token.json").write_text("TOKEN")
    return claude


def describe_stage_claude_config():
    """Allowlist copy: config in, credentials never."""

    def it_copies_allowlisted_config_only(tmp_path: Path):
        home = tmp_path / "home"
        _make_claude_home(home)
        dest = tmp_path / "stage"

        stage_claude_config(home, dest)

        assert (dest / "settings.json").read_text() == '{"theme": "dark"}'
        assert (dest / "CLAUDE.md").read_text() == "# project memory"
        assert (dest / "commands" / "foo.md").read_text() == "do foo"

    def it_never_copies_credentials_or_tokens(tmp_path: Path):
        home = tmp_path / "home"
        _make_claude_home(home)
        dest = tmp_path / "stage"

        stage_claude_config(home, dest)

        # Default-deny: anything outside the allowlist is absent, in particular
        # credential/token-bearing files.
        assert not (dest / ".credentials.json").exists()
        assert not (dest / "auth-token.json").exists()
        copied = {p.name for p in dest.iterdir()}
        assert not any("credential" in n or "token" in n or "auth" in n for n in copied)

    def it_is_a_noop_for_missing_source_dir(tmp_path: Path):
        """No ~/.claude on the host -> dest is created but empty (no error)."""
        home = tmp_path / "empty-home"
        dest = tmp_path / "stage"

        stage_claude_config(home, dest)

        assert dest.exists()
        assert list(dest.iterdir()) == []

    def it_copies_only_existing_allowlist_entries(tmp_path: Path):
        """Allowlist entries absent on the host are simply skipped."""
        home = tmp_path / "home"
        claude = home / ".claude"
        claude.mkdir(parents=True)
        (claude / "settings.json").write_text("{}")
        dest = tmp_path / "stage"

        stage_claude_config(home, dest)

        assert (dest / "settings.json").exists()
        assert not (dest / "CLAUDE.md").exists()
        assert not (dest / "commands").exists()

    def it_skips_dangling_symlinks_in_copied_dirs(tmp_path: Path):
        """A stale symlink under skills/ (common in real ~/.claude) is skipped, not fatal."""
        home = tmp_path / "home"
        skills = home / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "good.md").write_text("ok")
        (skills / "dangling").symlink_to(tmp_path / "nonexistent-target")
        dest = tmp_path / "stage"

        stage_claude_config(home, dest)  # must not raise

        assert (dest / "skills" / "good.md").read_text() == "ok"
        assert not (dest / "skills" / "dangling").exists()
