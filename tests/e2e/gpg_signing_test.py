"""
End-to-end test for signed commits in the cage: `ltd --gpg-key-id <key>`.

THE BUG THIS PINS. `--gpg-key-id` used to bind the host `~/.gnupg` into the cage
READ-ONLY. gpg-agent creates sockets and lockfiles *inside* GNUPGHOME, so on a
stock setup it could not start and every `git commit` failed:

    gpg: failed to create temporary file '.../.gnupg/.#lk0x...': Read-only file system
    gpg: can't connect to the gpg-agent: Read-only file system
    gpg: signing failed: No agent running

The fix stages a disposable COPY of the host keyring in the instance cache dir
and mounts THAT read-write, so gpg-agent runs and the host keyring is never
written by the cage.

DEPLOY SKEW -- why this runs the installed `ltd`, not `uv run`: the previous
version of this file spun up `npx @devcontainers/cli` against a hand-placed
`~/.claude/.devcontainer/devcontainer.json` and SKIPPED when that file was
absent, so the real path (modify_config's mount + postStartCommand) had no
coverage at all. This invokes the deployed console script and prints which
artifact it ran, mirroring tests/e2e/coding_agent_test.py.

OWN THE PRECONDITION -- the test never reads or depends on the developer's real
`~/.gnupg`. It generates a throwaway, passphrase-free signing key under an
isolated $HOME and points `ltd` at that HOME, so the run is deterministic and
the host keyring is untouched.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

FIXTURE_UID = "LTD E2E Signing <ltd-e2e@example.invalid>"

# Sign a commit in a throwaway repo inside the cage, then verify the signature.
# `-S` is redundant (ltd sets commit.gpgsign) but makes a signing failure loud.
SIGN_AND_VERIFY = """
set -e
rm -rf /tmp/gpg-sign-e2e
mkdir -p /tmp/gpg-sign-e2e
cd /tmp/gpg-sign-e2e
git init -q
echo hello > file.txt
git add file.txt
git commit -q -S -m 'signed commit'
git log --show-signature -1
"""


def _ltd_binary() -> str | None:
    """Resolve the DEPLOYED `ltd` console script, excluding the venv shadow.

    Same resolution as tests/e2e/coding_agent_test.py: LTD_BIN wins, otherwise
    `ltd`/`lamp-the-djinn` on PATH with the active virtualenv's bin dir removed,
    so `uv run pytest` cannot silently exercise the editable source install.
    """
    override = os.environ.get("LTD_BIN")
    if override:
        return override

    venv_bin = (Path(sys.prefix) / "bin").resolve()
    search = os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p).resolve() != venv_bin
    )
    return shutil.which("ltd", path=search) or shutil.which("lamp-the-djinn", path=search)


def _require_e2e_prerequisites() -> str:
    """Skip unless Docker, host gpg, and a deployed `ltd` are all available."""
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    if shutil.which("gpg") is None:
        pytest.skip("gpg not available on the host (needed to build the fixture keyring)")
    ltd = _ltd_binary()
    if ltd is None:
        pytest.skip("ltd/lamp-the-djinn console script not installed on PATH (set LTD_BIN)")
    # Always surface WHICH artifact ran -- a wrong-binary e2e is how the EROFS
    # bug shipped green before. If this points into a .venv, the test is lying.
    print(f"\n[e2e] exercising deployed artifact: {ltd}")
    return ltd


def _generate_fixture_key(home: Path) -> str:
    """Create a passphrase-free signing key in ``home/.gnupg`` and return its ID.

    Passphrase-free on purpose: an agent commits without a TTY, so a prompting
    key would hang rather than fail -- a different bug than the one pinned here.
    """
    gnupg = home / ".gnupg"
    gnupg.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = {**os.environ, "GNUPGHOME": str(gnupg)}
    subprocess.run(
        [
            "gpg",
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            FIXTURE_UID,
            "ed25519",
            "sign",
            "never",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    listed = subprocess.run(
        ["gpg", "--list-secret-keys", "--with-colons", FIXTURE_UID],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    fingerprint = next(line.split(":")[9] for line in listed.stdout.splitlines() if line.startswith("fpr:"))
    # Leave no agent holding sockets in the fixture keyring before it is copied.
    subprocess.run(["gpgconf", "--homedir", str(gnupg), "--kill", "gpg-agent"], capture_output=True, env=env)
    return fingerprint


def _isolated_env(home: Path) -> dict[str, str]:
    env = {**os.environ, "HOME": str(home)}
    env.pop("GNUPGHOME", None)
    return env


def describe_signing_commits_in_the_cage():
    """`ltd --gpg-key-id KEY` must produce verifiable signed commits."""

    def it_signs_a_commit_with_the_host_key(tmp_path: Path):
        """A cage started with --gpg-key-id signs, and the signature verifies.

        Red on the shipped read-only `~/.gnupg` bind: gpg-agent cannot create its
        socket, so `git commit -S` dies with "Read-only file system" / "No agent
        running" and no signature is ever made.
        """
        ltd = _require_e2e_prerequisites()

        home = tmp_path / "home"
        home.mkdir()
        key_id = _generate_fixture_key(home)
        project = tmp_path / "project"
        project.mkdir()

        result = subprocess.run(
            [
                ltd,
                "--gpg-key-id",
                key_id,
                "--git-user-name",
                "LTD E2E",
                "--git-user-email",
                "ltd-e2e@example.invalid",
                "--shell",
                SIGN_AND_VERIFY,
            ],
            cwd=project,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_isolated_env(home),
            timeout=900,
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert "read-only file system" not in combined.lower(), (
            f"gpg hit a read-only GNUPGHOME -- the cage keyring must be a writable "
            f"staged copy.\nrc={result.returncode}\n{combined}"
        )
        assert result.returncode == 0, f"signed commit failed in the cage (rc={result.returncode}).\n{combined}"
        assert "Good signature" in combined, f"commit was not verifiably signed.\n{combined}"

    def it_leaves_the_host_keyring_unwritten(tmp_path: Path):
        """The cage must not create agent sockets or lockfiles in the host keyring.

        This is the security half of the fix: signing works because the cage gets
        a COPY, not because the real `~/.gnupg` became writable.
        """
        ltd = _require_e2e_prerequisites()

        home = tmp_path / "home"
        home.mkdir()
        key_id = _generate_fixture_key(home)
        gnupg = home / ".gnupg"
        before = sorted(p.name for p in gnupg.iterdir())
        project = tmp_path / "project"
        project.mkdir()

        subprocess.run(
            [ltd, "--gpg-key-id", key_id, "--shell", SIGN_AND_VERIFY],
            cwd=project,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_isolated_env(home),
            timeout=900,
        )

        after = sorted(p.name for p in gnupg.iterdir())
        assert after == before, f"the cage wrote into the host keyring: {set(after) - set(before)}"

        # The copy holds private key material, so it must not outlive the cage.
        leftovers = list((home / ".cache" / "lamp-the-djinn").glob("workspace-*/gnupg-stage"))
        assert leftovers == [], f"staged keyring copies survived the run: {leftovers}"
