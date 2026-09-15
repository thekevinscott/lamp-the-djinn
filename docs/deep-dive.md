# Deep Dive

How lamp-the-djinn actually contains an untrusted agent: the two swappable
seams, the firewall, and the trust tiers. The full design lives in
[ARCHITECTURE.md](https://github.com/thekevinbot/lamp-the-djinn/blob/main/ARCHITECTURE.md);
this page is the working mental model.

## The two seams

The design separates **what isolates the agent** from **what model serves
it**, so each can vary independently behind one interface.

### Isolation seam

The agent runs in a Docker cage. `--runtime` picks the OCI runtime:

- **`runc` (default)** — stock Docker. `auto` resolves here; no flag needed.
- **`runsc` (gVisor)** — kernel-level isolation, but it **breaks the egress
  firewall** (gVisor's network stack bypasses the cage's iptables), so it's
  opt-in only.
- **`kata-runtime`** — VM-backed isolation; heavier, opt-in.
- **fly** — the same cage shipped to a remote Fly.io Firecracker microVM
  (scaffolded in `fly/`).

A requested runtime Docker doesn't have falls back to `runc` with a warning —
a run never hard-fails on a missing runtime.

### Provider seam

Every harness talks to exactly one endpoint: a **LiteLLM proxy on the host**.
The proxy holds the real credentials (OpenRouter key, local llama.cpp); the
cage only ever sees the proxy's base URL and a placeholder key. When you opt
in with `--model` / `--proxy-url` (or `LTD_MODEL` / `LTD_PROXY_URL`), ltd
injects both wire-format families into the cage — `OPENAI_*` for OpenAI-style
harnesses, `ANTHROPIC_*` for Claude Code — and the harness picks up whichever
it speaks.

Run the proxy with hot-reloading config:

```bash
docker compose up -d --watch   # syncs litellm/config.yaml on every edit
```

Edit `litellm/config.yaml` to add models — local llama.cpp, OpenRouter, or any
LiteLLM backend. Bare `ltd` with no `--model` engages no proxy at all: the
harness uses its own config.

## The firewall

Default-deny egress. `init-firewall.sh` runs at cage startup and allows only:

- The baked-in domain allowlist (npm, PyPI, GitHub, …).
- A machine-local supplement at `~/.config/lamp-the-djinn/allowed-domains.txt`.
- A per-run file via `--allow-domains-file` (or `LTD_ALLOW_DOMAINS_FILE`).

Both supplements are mounted **read-only** and read once at startup, before
the agent runs — the agent can never widen its own egress. The cage reaches
the host (for the proxy) via `host.docker.internal`, mapped explicitly to the
docker bridge gateway.

## Trust tiers

ltd is strict by default; `--trusted` relaxes exactly one thing.

- **Strict (default):** the cage gets a **disposable copy** of an allowlisted
  subset of `~/.claude` (`settings.json`, `CLAUDE.md`, `commands`, `agents`,
  `skills`, `hooks`) — never `.credentials.json` or anything bearing
  credentials. The agent's config writes are discarded on exit. Session
  transcripts (`~/.claude/projects`, `history.jsonl`) are mounted separately,
  read-write, so `--continue` keeps working.
- **`--trusted`:** live read-write bind of the host `~/.claude`, plus a
  writable harness package cache so `npx`/`uvx` don't re-download every run.
  Untrusted runs use an ephemeral in-container cache instead — deliberately,
  because npm writes to its cache even while fetching, so a read-only cache
  mount fails with `EROFS`.

## Credential persistence

`~/.cache/lamp-the-djinn/auth` is bind-mounted **read-write** into the cage at
`~/.config/ltd-auth` so harness sessions survive across runs. The principle:
**anything in this volume is readable by the untrusted agent.** Persist only
scoped, revocable credentials there. The model API key never enters the cage
(it stays in the proxy), and your primary git identity stays out — push
host-side, or supply a fine-grained, single-repo, revocable PAT.

## The four load-bearing controls

Security rests on all four, not on any single fence:

1. **Default-deny egress** — the harness reaches models only through the proxy.
2. **No credentials in the cage** — secrets live in the gitignored `.env`; the
   agent gets a placeholder proxy token.
3. **Ephemeral cage** — destroyed on exit; `git reset --hard` is the undo.
4. **Diff review** — you review what the agent produced before it leaves.

## Next steps

- [Troubleshooting](./troubleshooting/) — GPG signing and mounting extra
  folders.
- [ARCHITECTURE.md](https://github.com/thekevinbot/lamp-the-djinn/blob/main/ARCHITECTURE.md)
  — the full design document.
