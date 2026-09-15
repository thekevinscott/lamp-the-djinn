"""
End-to-end matrix: runtime x agent x invocation-mode, against the DEPLOYED `ltd`.

This pins the generalization promise of `ltd` -- that it is harness-agnostic and
runtime-agnostic -- by actually exercising the cartesian product the user asked
for:

    * agents .... pi (@earendil-works/pi-coding-agent) and claude (Claude Code)
    * runtimes .. runc (the default) and kata (the VM-isolated runtime)
    * modes ..... non-interactive (`-p`/piped) and interactive (a real PTY/TUI)

NON-INTERACTIVE cells do a REAL authenticated turn through the LiteLLM proxy and
assert the agent produced clean output with no wiring failure (EROFS, connection
error, context-window/credit errors, provider-not-found). They are the proof
that ltd correctly wires an arbitrary harness to the proxy.

INTERACTIVE cells launch the agent in a real PTY (via curtaincall) and assert the
agent's interactive UI boots to a known ready-state and stays alive -- the proof
that ltd's TTY invocation path works. They deliberately do NOT drive a full turn
through the TUI: that is brittle across agent versions (onboarding screens, theme
pickers) and the non-interactive cells already prove the proxy turn. The division
of labor is intentional -- PTY path here, model turn there.

DEPLOY SKEW -- same discipline as tests/e2e/coding_agent_test.py: we invoke the
installed `ltd` CONSOLE SCRIPT, never `uv run` against `src/`, so the test cannot
go green against the source while the shipped binary is broken. `_ltd_binary()`
resolves the real artifact (excluding the venv shadow) and prints which one ran.

pi and claude are both PREINSTALLED in the cage image, so the cells invoke them
by name rather than via `npx -y <pkg>` (which re-downloads the harness on every
untrusted run). `describe_what_the_cage_image_ships` is what pins that property;
these cells depend on it.

OWN THE PRECONDITION -- pi does not read OPENAI_BASE_URL; left alone it hits
api.openai.com and dies behind the cage firewall. So each pi cell CONSTRUCTS the
exact provider config pi needs (`<dir>/models.json` -> a custom `ltd` provider
pointed at the proxy), mounts it with `-v`, and points pi at it with
PI_CODING_AGENT_DIR. Nothing here depends on ambient developer state.

The matrix cells stage that config under `tmp_path` (i.e. `/tmp/...`), where a
path-identity `-v` mount lands correctly inside the cage. That deliberately does
NOT exercise the case the user actually hits: pi's real config lives under
`~/.pi` (HOME-relative), and the cage user's HOME (`/home/node`) differs from the
host's, so a naive path-identity mount of a `$HOME` path lands where pi never
looks. `describe_mounting_pi_config_from_the_host_home` pins that real path --
config UNDER `$HOME`, bare `-v`, command typed as one quoted string.

ENVIRONMENT -- this is a local-only e2e (Docker + a configured LiteLLM proxy; it
never runs in CI and is attested instead). Defaults match this project's proven
working setup; every knob is overridable:

    LTD_BIN .............................. deployed ltd to exercise
    LTD_E2E_PROXY_PROBE_URL .............. reachability gate (default :4000/v1/models)
    LTD_E2E_PI_MODEL ..................... pi model id in models.json (default qwen;
                                          must actually respond -- the 3B `local`
                                          returns empty under pi, and `glm-5.2`
                                          402s because pi always asks for 65536 tokens)
    LTD_E2E_CLAUDE_MODEL ................. claude model via proxy (default glm-5.2)
    LTD_E2E_CLAUDE_MAX_OUTPUT_TOKENS ..... claude output cap (default 4096)
    LTD_E2E_ANTHROPIC_PROXY_URL .......... ltd's anthropic base (default :4000)
    LTD_E2E_PI_BASE_URL .................. pi provider baseUrl (default :4000/v1)
    LTD_PROXY_API_KEY .................... proxy key (default lamp-the-djinn, matches ltd)
    LTD_E2E_SENTINEL ..................... soft-checked echo word (default BANANA)

Any cell skips loudly when its precondition is absent: no Docker, no deployed
ltd, proxy unreachable, an empty model env, or (for kata cells) no kata runtime.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from curtaincall.expect import expect

pytestmark = [pytest.mark.e2e, pytest.mark.claude]

SENTINEL = os.environ.get("LTD_E2E_SENTINEL", "BANANA")
PI_MODEL = os.environ.get("LTD_E2E_PI_MODEL", "qwen")
CLAUDE_MODEL = os.environ.get("LTD_E2E_CLAUDE_MODEL", "glm-5.2")
CLAUDE_MAX_TOKENS = os.environ.get("LTD_E2E_CLAUDE_MAX_OUTPUT_TOKENS", "4096")
ANTHROPIC_PROXY_URL = os.environ.get("LTD_E2E_ANTHROPIC_PROXY_URL", "http://host.docker.internal:4000")
PI_BASE_URL = os.environ.get("LTD_E2E_PI_BASE_URL", "http://host.docker.internal:4000/v1")
PROXY_API_KEY = os.environ.get("LTD_PROXY_API_KEY", "lamp-the-djinn")
PROXY_PROBE_URL = os.environ.get("LTD_E2E_PROXY_PROBE_URL", "http://127.0.0.1:4000/v1/models")
# Tiny image used to prove kata can actually START a container (not just be listed).
KATA_PROBE_IMAGE = os.environ.get("LTD_E2E_KATA_PROBE_IMAGE", "alpine")

# Specific failure signatures we have actually hit wiring agents to the proxy.
# Each is a real bug class, not generic prose that could appear in help text, so
# a match means a genuine wiring/turn failure -- never a false positive.
ERROR_MARKERS = (
    "erofs",
    "read-only file system",
    "connection error",
    "econnrefused",
    "requires more credits",  # OpenRouter 402: agent asked for more tokens than the key affords
    "contextwindowexceeded",  # prompt exceeded the model's context
    "not found for provider",  # provider/model id did not resolve
    "no models available",
    "invalid api key",
    "litellm.apierror",
)


def _ltd_binary() -> str | None:
    """Resolve the DEPLOYED `ltd`, excluding the venv shadow. See coding_agent_test.py."""
    override = os.environ.get("LTD_BIN")
    if override:
        return override
    venv_bin = (Path(sys.prefix) / "bin").resolve()
    search = os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p).resolve() != venv_bin
    )
    return shutil.which("ltd", path=search) or shutil.which("lamp-the-djinn", path=search)


def _proxy_reachable(url: str) -> bool:
    """True if the proxy answers at all. ANY HTTP response proves reachability;
    only a connection-level failure (refused/timeout/DNS) counts as down."""
    try:
        urllib.request.urlopen(url, timeout=5)  # noqa: S310 -- local fixed URL
        return True
    except urllib.error.HTTPError:
        return True  # 401/404/etc -- the proxy is up, it just answered non-200
    except (urllib.error.URLError, OSError):
        return False


def _docker_runtimes() -> set[str]:
    """Names of runtimes Docker knows about (e.g. {"runc", "kata", "nvidia"})."""
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return set()
    if r.returncode != 0:
        return set()
    try:
        return set(json.loads(r.stdout).keys())
    except (json.JSONDecodeError, AttributeError):
        return set()


def _require_cage() -> str:
    """Skip unless Docker and a deployed ltd are present -- enough to run a cage.

    Split out from _require_infra so a cell that only inspects the cage IMAGE
    does not skip for an unrelated reason (an unreachable model proxy)."""
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    ltd = _ltd_binary()
    if ltd is None:
        pytest.skip("ltd/lamp-the-djinn console script not installed on PATH (set LTD_BIN)")
    # A wrong-binary e2e is how the EROFS bug shipped green; always say which ran.
    print(f"\n[e2e] exercising deployed artifact: {ltd}")
    return ltd


def _require_infra() -> str:
    """Skip unless Docker, a deployed ltd, and a reachable proxy are all present.
    Returns the ltd binary path and prints which artifact will run."""
    ltd = _require_cage()
    if not _proxy_reachable(PROXY_PROBE_URL):
        pytest.skip(f"LiteLLM proxy not reachable at {PROXY_PROBE_URL} (set LTD_E2E_PROXY_PROBE_URL)")
    return ltd


def _require_kata() -> None:
    """Skip unless kata can actually START a container.

    `docker info` listing a 'kata' runtime is necessary but NOT sufficient: on a
    host where kata is wired as a containerd shim (no OCI `create` verb), the name
    shows up but `docker run --runtime kata` dies at setup with
    `OCI runtime create failed: Invalid command "create"`. A nominal list-check
    would turn that host-config gap into a red cell; the honest reading is "kata
    is effectively absent here". So we probe for real -- run a trivial container
    under kata -- and skip (not fail) on any failure."""
    if "kata" not in _docker_runtimes():
        pytest.skip("kata runtime not registered in Docker (skipping kata cell)")
    try:
        probe = subprocess.run(
            ["docker", "run", "--rm", "--runtime", "kata", KATA_PROBE_IMAGE, "true"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        pytest.skip(f"kata runtime present but its smoke probe could not run: {exc}")
    if probe.returncode != 0:
        pytest.skip(
            "kata runtime is registered but cannot start a container on this host "
            f"(non-functional): {probe.stderr.strip() or probe.stdout.strip()}"
        )


def _require_model(agent: str) -> str:
    """The model env for this agent, or skip loudly if it was blanked out."""
    model = PI_MODEL if agent == "pi" else CLAUDE_MODEL
    if not model.strip():
        knob = "LTD_E2E_PI_MODEL" if agent == "pi" else "LTD_E2E_CLAUDE_MODEL"
        pytest.skip(f"{knob} is empty -- set it to a model your proxy serves")
    return model


def _write_pi_provider(root: Path, model_id: str) -> Path:
    """Construct the exact provider config pi needs and return its dir.

    pi resolves models from `<PI_CODING_AGENT_DIR>/models.json`, NOT from
    OPENAI_BASE_URL. We register a single `ltd` provider pointed at the proxy
    with one explicit model entry -- an override-only provider (baseUrl, no
    models[]) will not resolve an arbitrary id. The OpenAI SDK appends
    /chat/completions to baseUrl, so baseUrl must end in /v1.
    """
    agent_dir = root / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "providers": {
            "ltd": {
                "baseUrl": PI_BASE_URL,
                "apiKey": PROXY_API_KEY,
                "api": "openai-completions",
                "models": [
                    {"id": model_id, "name": model_id, "contextWindow": 8192, "maxTokens": 2048},
                ],
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(config))
    return agent_dir


def _assert_clean_turn(label: str, rc: int, stdout: str, stderr: str) -> None:
    """A non-interactive cell passed iff: no wiring failure, the binary exited 0,
    and the agent actually emitted output. The sentinel is logged, not required
    (a 3B local model cannot reliably echo an exact word)."""
    combined = f"{stdout}\n{stderr}"
    low = combined.lower()
    hit = next((m for m in ERROR_MARKERS if m in low), None)
    assert hit is None, f"[{label}] proxy-wiring failure -- saw {hit!r}\nrc={rc}\n{combined}"
    assert rc == 0, f"[{label}] agent exited non-zero (rc={rc}) -- turn did not complete\n{combined}"
    assert stdout.strip(), f"[{label}] agent produced no output -- turn was vacuous\n{combined}"
    got_sentinel = SENTINEL.lower() in low
    print(f"[{label}] rc=0, output non-empty, sentinel {SENTINEL!r} present: {got_sentinel}")


@pytest.fixture
def reap_cages():
    """Reap ONLY the cage containers this test creates.

    ltd starts a persistent container (`devcontainer up`) and then execs the
    agent into it; the container outlives the agent, so without this every cell
    would leak one. We snapshot the `clanker.instance`-labelled containers before
    and after and force-remove exactly the difference -- never touching the
    developer's pre-existing cages.
    """

    def snapshot() -> set[str]:
        r = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=clanker.instance"],
            capture_output=True,
            text=True,
        )
        return set(r.stdout.split())

    before = snapshot()
    yield
    new = snapshot() - before
    for cid in new:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, text=True)
    if new:
        print(f"[e2e] reaped {len(new)} cage container(s): {sorted(new)}")


def describe_running_an_agent_non_interactively():
    """`ltd ... <agent> -p <prompt>` must complete a real turn through the proxy."""

    @pytest.mark.parametrize(
        "agent,runtime",
        [
            pytest.param("pi", "runc", id="pi-runc"),
            pytest.param("pi", "kata", id="pi-kata"),
            pytest.param("claude", "runc", id="claude-runc"),
            pytest.param("claude", "kata", id="claude-kata"),
        ],
    )
    def it_completes_a_real_turn_through_the_proxy(agent, runtime, tmp_path, reap_cages):
        ltd = _require_infra()
        if runtime == "kata":
            _require_kata()
        model = _require_model(agent)
        label = f"{agent}-{runtime}"
        prompt = f"Reply with exactly one word and nothing else: {SENTINEL}"
        env = {**os.environ}

        if agent == "pi":
            agent_dir = _write_pi_provider(tmp_path, model)
            argv = [
                ltd,
                "--model",
                model,
                "--runtime",
                runtime,
                "-v",
                str(agent_dir),
                "-e",
                f"PI_CODING_AGENT_DIR={agent_dir}",
                "pi",
                "-p",
                "--model",
                f"ltd/{model}",
                prompt,
            ]
        else:
            env["LTD_ANTHROPIC_PROXY_URL"] = ANTHROPIC_PROXY_URL
            argv = [
                ltd,
                "--model",
                model,
                "--runtime",
                runtime,
                "-e",
                f"CLAUDE_CODE_MAX_OUTPUT_TOKENS={CLAUDE_MAX_TOKENS}",
                "claude",
                "-p",
                prompt,
            ]

        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
        _assert_clean_turn(label, result.returncode, result.stdout, result.stderr)


def describe_running_an_agent_interactively():
    """`ltd ... <agent>` in a real PTY must boot the agent's interactive UI."""

    @pytest.mark.parametrize(
        "agent",
        [
            pytest.param("pi", id="pi-runc"),
            pytest.param("claude", id="claude-runc"),
        ],
    )
    def it_boots_the_agent_tui_in_a_pty(agent, tmp_path, terminal, reap_cages):
        ltd = _require_infra()
        model = _require_model(agent)
        label = f"{agent}-interactive"

        if agent == "pi":
            agent_dir = _write_pi_provider(tmp_path, model)
            cmd = " ".join(
                [
                    ltd,
                    "--model",
                    model,
                    "--runtime",
                    "runc",
                    "-v",
                    str(agent_dir),
                    "-e",
                    f"PI_CODING_AGENT_DIR={agent_dir}",
                    "pi",
                    "--model",
                    f"ltd/{model}",
                ]
            )
            term_env = None
            ready = re.compile(r"pi v\d")  # version banner -- stable across themes/builds
        else:
            cmd = " ".join(
                [
                    ltd,
                    "--model",
                    model,
                    "--runtime",
                    "runc",
                    "-e",
                    f"CLAUDE_CODE_MAX_OUTPUT_TOKENS={CLAUDE_MAX_TOKENS}",
                    "claude",
                ]
            )
            term_env = {"LTD_ANTHROPIC_PROXY_URL": ANTHROPIC_PROXY_URL}
            ready = "Welcome to Claude Code"

        # Wide enough that the ready banner is never line-wrapped; tall history so
        # it stays findable even after the cage build noise scrolls past.
        term = terminal(cmd, rows=40, cols=120, env=term_env)

        # The cage must build AND the agent must boot -- minutes, not seconds.
        expect(term.get_by_text(ready)).to_be_visible(timeout=480)

        # Booting is not enough: the TUI must still be alive (didn't crash post-banner)
        # and the screen must be free of any wiring failure.
        assert term.is_alive, f"[{label}] agent TUI exited right after its banner"
        buffer = "\n".join("".join(row) for row in term.get_buffer()).lower()
        hit = next((m for m in ERROR_MARKERS if m in buffer), None)
        assert hit is None, f"[{label}] interactive boot showed a wiring failure -- saw {hit!r}"
        print(f"[{label}] interactive UI reached ready-state and stayed alive")


def describe_mounting_pi_config_from_the_host_home():
    """The real user invocation: `ltd -v ~/.pi '<pi command>'`.

    This is the path the matrix cells above sidestep by staging under /tmp. Two
    faults compound on the deployed binary and BOTH must be fixed for this to go
    green:

      1. Quoted command -- the user types the whole command as one quoted string
         (`ltd -v ~/.pi 'npx -y @earendil-works/pi-coding-agent ...'`). A single
         REMAINDER token containing whitespace must be split into argv, or
         `devcontainer exec` tries to run a binary literally named with spaces.

      2. Home-relative mount -- `~/.pi` is under `$HOME`. A bare `-v` of a path
         under the host home must land at the cage user's home (the same remap
         ltd already does by hand for ~/.claude, ~/.ssh, ~/.gnupg), or the config
         is mounted where pi never looks and pi reports "No models available".

    OWN THE PRECONDITION: the config dir is created UNDER `$HOME` (NOT /tmp --
    only a HOME-relative mount triggers the host/cage HOME mismatch), staged with
    the exact provider pi needs, and removed afterward. Nothing depends on the
    developer's real ~/.pi.
    """

    def it_resolves_a_model_from_a_home_mounted_config(reap_cages):
        ltd = _require_infra()
        model = _require_model("pi")
        # The mount MUST be under $HOME for this to mean anything: a /tmp path
        # mounts path-identity and would pass even on the broken binary.
        cfg_root = Path.home() / f".ltd-e2e-pi-home-{os.getpid()}"
        try:
            _write_pi_provider(cfg_root, model)  # -> cfg_root/agent/models.json
            # The cage user's HOME is /home/node, so a correctly home-mapped `-v`
            # lands cfg_root there; pi reads its config from that mapped path.
            cage_agent_dir = f"/home/node/{cfg_root.name}/agent"
            pi_cmd = f'pi -p --model ltd/{model} "Reply with exactly one word and nothing else: {SENTINEL}"'
            argv = [
                ltd,
                "--model",
                model,
                "--runtime",
                "runc",
                "-v",
                str(cfg_root),
                "-e",
                f"PI_CODING_AGENT_DIR={cage_agent_dir}",
                pi_cmd,  # ONE quoted token, exactly as the user types it
            ]
            result = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env={**os.environ},
                timeout=600,
            )
            _assert_clean_turn("pi-home-mount", result.returncode, result.stdout, result.stderr)
        finally:
            shutil.rmtree(cfg_root, ignore_errors=True)


def describe_tearing_down_the_cage():
    """`ltd <cmd>` must not leak its cage container after the command exits.

    ltd starts a PERSISTENT container (`devcontainer up`) and runs the command
    inside it via `devcontainer exec`. When the command exits, ltd must tear that
    container down -- otherwise every single run orphans one cage (the leak that
    forced the `reap_cages` fixture to exist in the first place). This cell does
    NOT use reap_cages: leaking is exactly what it is here to catch, so it
    asserts on the survivor set itself and only cleans up in `finally`.
    """

    def it_leaves_no_cage_container_after_the_command_exits():
        ltd = _require_infra()

        def cages() -> set[str]:
            r = subprocess.run(
                ["docker", "ps", "-aq", "--filter", "label=clanker.instance"],
                capture_output=True,
                text=True,
            )
            return set(r.stdout.split())

        before = cages()
        leaked: set[str] = set()
        try:
            # `true` exits immediately and needs no model -- this is purely a
            # container-lifecycle assertion, not a turn.
            result = subprocess.run(
                [ltd, "--runtime", "runc", "true"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env={**os.environ},
                timeout=300,
            )
            leaked = cages() - before
            assert not leaked, (
                f"ltd leaked {len(leaked)} cage container(s) {sorted(leaked)} after "
                f"`ltd true` exited (rc={result.returncode}) -- every run orphans a cage.\n"
                f"{result.stdout}\n{result.stderr}"
            )
        finally:
            for cid in leaked:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, text=True)

    def it_tears_down_the_cage_when_ltd_is_terminated():
        """A clean exit is not the only way out. If the user closes the terminal
        (SIGHUP) or the process is killed (SIGTERM) while an interactive session
        is still up, ltd must STILL tear the cage down -- a `finally` alone does
        not run on a signal. We launch a long-lived in-cage command, wait for the
        cage, send SIGTERM to ltd, and assert the cage does not survive."""
        ltd = _require_infra()

        def cages() -> set[str]:
            r = subprocess.run(
                ["docker", "ps", "-aq", "--filter", "label=clanker.instance"],
                capture_output=True,
                text=True,
            )
            return set(r.stdout.split())

        before = cages()
        mine: set[str] = set()
        proc = subprocess.Popen(
            [ltd, "--runtime", "runc", "sleep 600"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ},
        )
        try:
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                mine = cages() - before
                if mine:
                    break
                if proc.poll() is not None:
                    pytest.fail(f"ltd exited before its cage came up (rc={proc.returncode})")
                time.sleep(2)
            assert mine, "ltd never started a cage within the timeout"

            proc.terminate()  # SIGTERM, as `kill` / a terminal teardown would
            proc.wait(timeout=90)

            survivors = cages() & mine
            assert not survivors, (
                f"cage(s) {sorted(survivors)} survived ltd's SIGTERM -- teardown did not run on the signal path"
            )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)
            for cid in cages() & mine:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, text=True)


def describe_what_the_cage_image_ships():
    """Harnesses the image PREINSTALLS, so a run never pays to fetch them.

    Every `npx -y <harness>` inside the cage is a fresh npm download: the
    harness-package cache is mounted only for `--trusted` runs (see
    modify_config), so the default untrusted run has no warm cache to hit. For a
    harness used on every single run that download is pure, repeated startup
    latency -- measured at ~3s for pi. The fix is the one already applied to
    Claude Code and the Playwright CLI: install it globally in the image.
    """

    def it_ships_pi_preinstalled(reap_cages):
        """`pi` must resolve to a global install inside the cage.

        `pi --version` alone is NOT enough: it passes just as well on a cage
        that downloaded pi on demand, which is the cost this pins away. The
        resolved PATH entry is what separates shipped-in-the-image from
        fetched-at-runtime, so assert on that -- an npx cache path is a failure.
        """
        ltd = _require_cage()
        # `command` is a shell builtin, so this needs --shell (`bash -c`) rather
        # than a bare argv command, which devcontainer exec would try to execvp.
        result = subprocess.run(
            [ltd, "--runtime", "runc", "--shell", "command -v pi"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env={**os.environ},
            timeout=600,
        )
        assert result.returncode == 0, (
            f"`pi` is not on PATH in the cage -- it is not preinstalled\n{result.stdout}\n{result.stderr}"
        )
        resolved = result.stdout.strip().splitlines()[-1].strip()
        assert "_npx" not in resolved, f"pi resolved to an npx cache, not the image: {resolved}"
        assert resolved.startswith("/usr/"), f"pi did not resolve to a global install: {resolved}"
        print(f"[cage-image] pi preinstalled at {resolved}")
