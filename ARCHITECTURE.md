# Architecture

lamp-the-djinn runs an untrusted coding agent ("the harness") inside a
disposable cage. The design has two seams so that *what isolates the agent* and
*what model serves it* can each vary independently behind a single interface.

## Isolation seam

One question: how strongly is the container isolated from the host? The CLI
resolves an OCI runtime and hands it to Docker; nothing else in the code path
changes.

- **local / gVisor (default)** — `detect_runtime("auto")` uses gVisor's `runsc`
  when it is registered with Docker, otherwise falls back to stock `runc`. Hosts
  without gVisor keep their existing behavior unchanged.
- **kata** — `--runtime kata-runtime` selects a VM-backed runtime when installed.
- **fly** — the same cage shipped to a remote Fly.io machine (see `fly/`).

A concrete runtime that Docker does not report falls back to `runc` with a
warning, so a run never hard-fails on a missing runtime. See
`detect_runtime` in `src/lamp_the_djinn/runtime.py`.

## Provider seam

One question: which model serves a request? Every harness talks to exactly one
local endpoint — the **LiteLLM proxy** — and never to a provider directly. The
proxy abstracts the backend:

- `--model local` → a local llama.cpp server.
- `--model <hosted>` → OpenRouter (or any LiteLLM-mapped backend).

Two wire formats are supported by `harness.provider_env`: OpenAI
(`OPENAI_BASE_URL`/`OPENAI_API_KEY`, used by Codex/Aider/custom) and Anthropic
(`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`, used by Claude Code). The harness
only ever sees a base URL, a key, and a model name.

## Harness model

A harness is the agent program run inside the cage (Claude Code, Codex, Aider,
or a raw command). Harnesses are fetched with `npx`/`uvx` at runtime. The
harness cache is **trust-gated**, because pointing a package manager at a
read-only mount fails: npm writes `_cacache/tmp` even while merely fetching
metadata, so a read-only cache dies with `EROFS` on the first fetch.

- A **trusted nightly refresh** runs on the *host*
  (`scripts/refresh-harness-cache.sh`) and pre-fetches packages into
  `~/.cache/lamp-the-djinn/harness-cache` with a cooldown window.
- **Trusted runs** (`--trusted`) mount that cache **read-write** and point
  in-container `UV_CACHE_DIR` / `npm_config_cache` at it, so repeated runs reuse
  pre-vetted packages instead of re-downloading.
- **Untrusted runs** (the default) mount **no** host cache and set **no** cache
  env: the cage uses its own writable, ephemeral in-container cache. It
  re-fetches each run, but never writes to a host path and never `EROFS`es.

The regression test for this lives in `tests/e2e/coding_agent_test.py` (the
deployed-artifact reproduction) and `tests/integration/harness_cache_test.py`
(the deterministic config decision).

Because the default run has no warm cache, an `npx -y <harness>` is a full npm
download on **every** run — ~3s for pi. Harnesses in routine use therefore ship
**preinstalled in the image**, globally, alongside Claude Code and the Playwright
CLI: `pi` and `claude` are on `PATH` in the cage, so invoking them costs nothing
at startup and the trust-gate tradeoff above never applies to them. The cost is
that their version tracks image builds rather than the registry; `npx -y` stays
available for a harness the image doesn't carry, or for pinning an older one.
`tests/e2e/agent_matrix_test.py` asserts pi resolves to a global install and not
to an npx cache.

## Load-bearing controls

The security model rests on four properties, not on any single fence:

1. **Default-deny egress** — outbound traffic is blocked except for a small
   allowlist; the harness reaches models only through the proxy.
2. **No credentials in the cage** — secrets live in the host's gitignored
   `.env`; the proxy holds the real keys, the agent gets only a placeholder
   proxy token.
3. **Ephemeral** — the cage is disposable; `git reset --hard` is the undo.
4. **Diff review** — the human reviews the produced diff before it leaves.

## Startup cost

The cage is created and torn down per run (`teardown_cage`), so everything
`devcontainer up` does is paid on every invocation -- there is no warm container
to amortize it against. That makes no-op work in that path worth removing.

`updateRemoteUserUID` is on by default for a non-root `remoteUser`, and the
devcontainer CLI honors it by building an extra derived image (tagged
`...-uid`) that `usermod`s the cage user to the host's ids. The cage's `node` is
uid/gid 1000 by construction (the Dockerfile renames whatever user the base
image left at 1000), so on a host that is also 1000 the build applies a rename
that changes nothing. `modify_config` sets `updateRemoteUserUID: false` in
exactly that case and leaves it alone otherwise -- both ids must match, because
a partial match would leave bind-mounted files wrong-grouped. Measured on a warm
host: 2.4s -> 2.0s for `up`.
