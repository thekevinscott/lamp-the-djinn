"""
Integration tests for the firewall functionality.

These tests verify that:
- Blocked domains are actually blocked
- Whitelisted domains are accessible
- Dynamic domain approval works
- A host-supplied --allow-domains-file opens extra egress for one cage, and the
  agent cannot widen it from inside (the file is mounted read-only)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import DevContainer

pytestmark = pytest.mark.e2e


def _ltd_binary() -> str | None:
    """Resolve the DEPLOYED `ltd` console script (NOT the venv editable shadow).

    Same rationale as tests/e2e/coding_agent_test.py: under `uv run pytest` the
    editable install puts an `ltd` in `.venv/bin` that runs the live source, so
    `shutil.which` would validate the source instead of the shipped artifact and
    hide deploy skew. We resolve `ltd` on PATH excluding the active venv's bin,
    honoring LTD_BIN for CI/local override.
    """
    override = os.environ.get("LTD_BIN")
    if override:
        return override

    venv_bin = (Path(sys.prefix) / "bin").resolve()
    search = os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p).resolve() != venv_bin
    )
    return shutil.which("ltd", path=search) or shutil.which("lamp-the-djinn", path=search)


def describe_firewall():
    """Tests for the iptables/ipset firewall."""

    def it_blocks_non_whitelisted_domains(devcontainer: DevContainer):
        """Verify that domains not in the whitelist are blocked."""
        # example.com is not in our whitelist
        result = devcontainer.exec(
            "curl --connect-timeout 5 -s https://example.com",
            timeout=15,
        )
        # Should fail - either connection refused or timeout
        assert result.returncode != 0, f"Expected blocked domain to fail, but curl succeeded: {result.stdout}"

    def it_allows_whitelisted_domains(devcontainer: DevContainer):
        """Verify that whitelisted domains are accessible."""
        # api.github.com is in our whitelist
        result = devcontainer.exec(
            "curl --connect-timeout 10 -s https://api.github.com/zen",
            timeout=20,
        )
        assert result.returncode == 0, f"Expected whitelisted domain to succeed: {result.stderr}"
        # GitHub zen endpoint returns a random quote
        assert len(result.stdout.strip()) > 0, "Expected non-empty response from GitHub"

    def it_allows_dynamically_approved_domains(devcontainer: DevContainer):
        """Verify that domains can be added to the whitelist at runtime."""
        # First verify httpbin.org is blocked
        result = devcontainer.exec(
            "curl --connect-timeout 5 -s https://httpbin.org/get",
            timeout=15,
        )
        # Should fail initially
        initial_blocked = result.returncode != 0

        # Add httpbin.org to the whitelist
        result = devcontainer.exec(
            "sudo /usr/local/bin/add-domain-to-firewall.sh httpbin.org",
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to add domain to firewall: {result.stderr}"

        # Now it should work
        result = devcontainer.exec(
            "curl --connect-timeout 10 -s https://httpbin.org/get",
            timeout=20,
        )
        assert result.returncode == 0, f"Domain should be accessible after approval: {result.stderr}"

        # Verify we got valid JSON back
        assert '"url"' in result.stdout, "Expected JSON response from httpbin"

        # Log whether it was initially blocked (informational)
        if not initial_blocked:
            print("Note: httpbin.org was already accessible (may be in user's approved list)")

    def it_rejects_invalid_domain_format(devcontainer: DevContainer):
        """Verify that invalid domain formats are rejected."""
        # Try to add an invalid domain
        result = devcontainer.exec(
            "sudo /usr/local/bin/add-domain-to-firewall.sh 'invalid domain with spaces'",
            timeout=10,
        )
        assert result.returncode != 0, "Should reject invalid domain format"
        assert "Invalid domain format" in result.stderr or "ERROR" in result.stderr

    def it_loads_domains_from_whitelist_file(devcontainer: DevContainer):
        """Verify that the domains file is loaded correctly."""
        # Check that the domains file exists
        result = devcontainer.exec(
            "cat /usr/local/share/whitelisted-domains.txt | grep -v '^#' | grep -v '^$' | wc -l",
            timeout=10,
        )
        assert result.returncode == 0
        domain_count = int(result.stdout.strip())
        assert domain_count > 20, f"Expected at least 20 domains, got {domain_count}"

        # Verify a known domain is in the file
        result = devcontainer.exec(
            "grep 'registry.npmjs.org' /usr/local/share/whitelisted-domains.txt",
            timeout=10,
        )
        assert result.returncode == 0, "registry.npmjs.org should be in whitelist file"


def describe_per_run_allow_domains_file():
    """`ltd --allow-domains-file FILE` opens extra egress for ONE cage, read-only.

    Drives the DEPLOYED `ltd` (not the bare devcontainer fixture), because the
    behavior under test is ltd's own flag -> read-only mount -> firewall pickup.

    Domain choice avoids IP collisions and the firewall's own self-test sentinels:
      - httpbin.org  : the per-run-allowed domain. NOT in the baked-in whitelist
                       and on AWS, so its IPs are distinct from example.com's.
      - example.com  : the still-blocked sentinel. init-firewall asserts this is
                       UNreachable during startup, so it stays a safe blocked probe.
    """

    def it_opens_a_listed_domain_keeps_others_blocked_and_stays_readonly(tmp_path: Path):
        if shutil.which("docker") is None:
            pytest.skip("docker not available")
        ltd = _ltd_binary()
        if ltd is None:
            pytest.skip("ltd/lamp-the-djinn console script not installed on PATH (set LTD_BIN)")
        print(f"\n[e2e] exercising deployed artifact: {ltd}")

        run_file = tmp_path / "this-task-domains.txt"
        run_file.write_text("httpbin.org\n")

        # One probe, three sentinels: listed domain reachable, unlisted blocked,
        # mounted file not writable.
        target = "/usr/local/share/ltd-allowed-domains.run.txt"
        probe = (
            "set +e; "
            "curl --connect-timeout 15 -s -o /dev/null https://httpbin.org/get "
            "&& echo ALLOWED_OK || echo ALLOWED_FAIL; "
            "curl --connect-timeout 5 -s -o /dev/null https://example.com "
            "&& echo BLOCKED_LEAK || echo BLOCKED_OK; "
            f"echo widen >> {target} 2>/tmp/werr "
            "&& echo WRITE_LEAK || echo WRITE_DENIED; "
            "cat /tmp/werr 2>/dev/null"
        )

        result = subprocess.run(
            [ltd, "--allow-domains-file", str(run_file), "bash", "-c", probe],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600,
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert "ALLOWED_OK" in combined, (
            f"listed domain httpbin.org was NOT reachable -- the run file didn't open egress.\n{combined}"
        )
        assert "BLOCKED_OK" in combined and "BLOCKED_LEAK" not in combined, (
            f"a non-listed domain (example.com) was reachable -- the file widened egress too far.\n{combined}"
        )
        assert "WRITE_DENIED" in combined and "WRITE_LEAK" not in combined, (
            f"the mounted domains file was WRITABLE from inside the cage -- the agent can widen its "
            f"own egress.\n{combined}"
        )
        assert "Read-only file system" in combined or "Permission denied" in combined, (
            f"expected an EROFS/permission error when writing the read-only mount.\n{combined}"
        )
