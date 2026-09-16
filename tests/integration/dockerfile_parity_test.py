"""
Integration tests pinning the shared invariants between the two cage Dockerfiles.

`.devcontainer/Dockerfile` is what CI builds and publishes to ghcr.io -- the
image `ltd` pulls by default. `src/lamp_the_djinn/devcontainer/Dockerfile` is
the copy embedded in the wheel, used as the local-build fallback when the pull
fails or `--build` is passed. Both run arbitrary agent workloads, so the tool
versions and base image they hand an agent must not drift apart by accident.

They also legitimately differ: only the packaged copy installs the Docker CLI
and a pinned global Playwright CLI (a devcontainer.json used purely to develop
this repo mounts no docker socket and needs neither), and only the published
image carries OCI build-metadata labels. This test does not assert byte
equality -- see the comments on each check for what is and isn't shared.

The real, controlled collaborator is the host filesystem: dockerfile_parse
reads the two files as they exist in this checkout. Nothing first-party is
mocked.
"""

import re
from pathlib import Path

import pytest
from dockerfile_parse import DockerfileParser

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
DEVCONTAINER_DOCKERFILE = REPO_ROOT / ".devcontainer" / "Dockerfile"
PACKAGED_DOCKERFILE = REPO_ROOT / "src" / "lamp_the_djinn" / "devcontainer" / "Dockerfile"

# Bumping one of these in only one image is exactly the drift this test exists
# to catch (see issue #88: PRs #79 and #85 each had to hand-patch both files).
SHARED_ARG_DEFAULTS = ("CLAUDE_CODE_VERSION", "PI_VERSION", "GIT_DELTA_VERSION", "PNPM_VERSION")

# RUN instructions that must be byte-identical between the two images,
# identified by a substring unique to each.
SHARED_RUN_NEEDLES = (
    "apt-get install",
    "pnpm@",
    "@anthropic-ai/claude-code@",
    "@earendil-works/pi-coding-agent@",
    "known_hosts",
)


def _run_containing(dfp: DockerfileParser, needle: str) -> str:
    matches = [s["value"] for s in dfp.structure if s["instruction"] == "RUN" and needle in s["value"]]
    assert len(matches) == 1, f"expected exactly one RUN instruction containing {needle!r}, found {len(matches)}"
    return matches[0]


def _copy_instructions(dfp: DockerfileParser) -> list[str]:
    return [s["value"] for s in dfp.structure if s["instruction"] == "COPY"]


def describe_dockerfile_parity():
    devcontainer = DockerfileParser(path=str(DEVCONTAINER_DOCKERFILE))
    packaged = DockerfileParser(path=str(PACKAGED_DOCKERFILE))

    def it_pins_the_same_playwright_base_image_version():
        # devcontainer hardcodes the tag (the "Update Base Image Digest"
        # workflow may append an `@sha256:...` pin to it); packaged
        # parameterizes it via PLAYWRIGHT_VERSION so the same ARG can also pin
        # the global playwright CLI installed later in that file. Compare the
        # version, not the full image reference, so a digest pin on one side
        # doesn't fail this check.
        version_re = re.compile(r"playwright:v([\d.]+)-noble")
        devcontainer_match = version_re.search(devcontainer.baseimage)
        packaged_match = version_re.search(packaged.baseimage)
        assert devcontainer_match, f"no playwright version found in {devcontainer.baseimage!r}"
        assert packaged_match, f"no playwright version found in {packaged.baseimage!r}"
        assert devcontainer_match.group(1) == packaged_match.group(1)

    def it_shares_the_same_tool_version_pins():
        for name in SHARED_ARG_DEFAULTS:
            assert devcontainer.args[name] == packaged.args[name], name

    def it_shares_the_same_run_instructions_for_common_setup():
        for needle in SHARED_RUN_NEEDLES:
            assert _run_containing(devcontainer, needle) == _run_containing(packaged, needle), needle

    def it_copies_the_same_firewall_scripts_and_uv():
        assert _copy_instructions(devcontainer) == _copy_instructions(packaged)

    def it_shares_the_same_environment_block():
        assert devcontainer.envs == packaged.envs
