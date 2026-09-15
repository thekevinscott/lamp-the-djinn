# lamp-the-djinn

A sandbox for running any coding agent with full autonomy, without risking your system.

**Docs:** https://thekevinbot.github.io/lamp-the-djinn/ — [Read the blog post](https://thekevinscott.com/sandbox-for-claude-code/) for more context.

## What It Solves

You want a coding agent to run with full autonomy (Claude Code's `--dangerously-skip-permissions`, or any other harness in YOLO mode) so it can work without constant interruptions. But you don't fully trust it — especially when it's driven by an open-weights model — not to [delete your hard drive](https://www.tomshardware.com/tech-industry/artificial-intelligence/googles-agentic-ai-wipes-users-entire-hard-drive-without-permission-after-misinterpreting-instructions-to-clear-a-cache-i-am-deeply-deeply-sorry-this-is-a-critical-failure-on-my-part) or quietly exfiltrate your secrets.

lamp-the-djinn runs **any** coding agent inside a Docker container — `claude`, `npx @anthropic/claude`, `aider`, or any command you pass. The container mounts only your project directory, so the agent can read and write your code but can't touch anything else on your system, and a default-deny network firewall blocks exfiltration. The model it talks to — local or hosted — is wired through a proxy that holds the real credentials, so they never enter the cage.

## Quick Start

```bash
uvx --from git+https://github.com/thekevinbot/lamp-the-djinn lamp-the-djinn
```

## Usage

The command after ltd's own options is what runs inside the cage:
`ltd [ltd-opts] <command...>`. The command's own flags are passed through
untouched (ltd's option parsing stops at the first command token).

```bash
ltd                          # bare: runs `claude --dangerously-skip-permissions`
ltd claude -p "fix the bug"  # the -p goes to claude, not ltd
ltd npx @anthropic/claude    # run an agent straight from npm
ltd --model glm-5.2 aider    # route a different harness through the proxy
ltd --safe-mode              # bare claude with permission prompts on
```

When you pass a command, a `--model`, or a `--proxy-url` (or set `LTD_MODEL` /
`LTD_PROXY_URL`), ltd wires the harness to a LiteLLM proxy on the host and
injects both provider env families (`OPENAI_*` and `ANTHROPIC_*`) so the agent
finds whichever it speaks. Bare `ltd` with none of these stays fully
backward-compatible: no proxy, just claude.

Some harnesses ignore provider env vars and read their own config file instead —
pi (`@earendil-works/pi-coding-agent`), for example, resolves providers only from
`~/.pi/agent/models.json`. Mount just that file with `-v`, and quote the whole
command as one string:

```bash
ltd -v ~/.pi/agent/models.json 'npx -y @earendil-works/pi-coding-agent'
```

Scope the mount to the single file the harness needs — not the whole `~/.pi`.
That directory also holds `auth.json` (your pi credentials), and **everything
mounted into the cage is readable by the untrusted agent**; mounting one file
keeps the secret out.

A `-v` path under your home maps to the **cage user's** home
(`~/.pi/agent/models.json` → the same path under the cage's home), because the
cage runs as `node`, not as you — so a plain path-identity mount of a home path
would land where the harness never looks. When that mount is a single file, ltd
also makes the parent directories Docker creates for it (here `~/.pi` and
`~/.pi/agent`) owned by the cage user, so a harness that writes *next to* the
file can do so — pi, for instance, creates its session dir at
`~/.pi/agent/sessions/`. A `-v` path outside your home keeps its own path. Point
pi's config at a `cage` provider whose `baseUrl` is
`http://host.docker.internal:4000/v1` (the proxy as seen from inside the cage).

## Configuration

For a dedicated GitHub identity (recommended for distinguishing AI commits from your own):

```bash
uvx --from git+https://github.com/thekevinbot/lamp-the-djinn lamp-the-djinn \
  --ssh-key-file ~/.ssh/id_ed25519_yourbot \
  --git-user-name yourbot \
  --git-user-email "yourbot@users.noreply.github.com" \
  --gpg-key-id YOUR_GPG_KEY_ID \
  --gh-token ghp_your_github_token
```

## Allowlisting extra egress domains

The cage ships a baked-in domain allowlist (npm, PyPI, GitHub, …); everything
else is blocked by default-deny egress. Two host-side ways to open more domains
without rebuilding the image:

- **Machine-local, all cages**: drop one domain per line in
  `~/.config/lamp-the-djinn/allowed-domains.txt`. ltd mounts it read-only into
  every cage and the firewall resolves it at startup. Use this for domains you
  always want reachable on this machine.
- **Per-run, this cage only**: pass `--allow-domains-file PATH` (or set
  `LTD_ALLOW_DOMAINS_FILE`). ltd mounts that file read-only into the single cage
  it launches, so only that run gets the extra domains.

```bash
ltd --allow-domains-file ./this-task-domains.txt 'claude -p "fetch the docs"'
```

Both files are mounted **read-only**: the firewall reads them once at startup,
before the agent runs, and the agent cannot edit them from inside the cage (the
mount is `EROFS`) — so the agent can never widen its own egress. A domain not in
the baked-in list, the machine-local file, or the per-run file stays blocked.

## How It Works

Two swappable seams (see [ARCHITECTURE.md](ARCHITECTURE.md) for the full design):

- **Isolation seam**: the agent runs in Docker, accessing only the mounted project directory. Uses gVisor (`runsc`) automatically when it's installed, else stock `runc`; a remote Fly (Firecracker microVM) backend is scaffolded in `fly/`.
- **Provider seam**: one LiteLLM proxy on the host fronts your local llama.cpp and OpenRouter (e.g. GLM-5.2); the cage only ever sees the proxy, never the real key.
- **Network firewall**: default-deny outbound; allowlisted domains only, with an opt-in proxy-only mode.
- **Cooldown cache**: harnesses are pre-fetched by a trusted nightly job with a minimum-release-age window and mounted read-only — supply-chain defense, so the untrusted agent never reaches a registry.
- **Git as undo**: lean on `git reset --hard` as your escape hatch.

## Credential Persistence

To let harness sessions survive across runs (e.g. an OAuth token an agent
writes after `login`), ltd bind-mounts a **writable** host directory
(`~/.cache/lamp-the-djinn/auth`) into the cage at
`/home/node/.config/ltd-auth`.

**Principle: anything in this volume is readable by the untrusted agent.**
The agent has full read access to everything you persist here, so treat it as
exposed. Concretely:

- **Persist only scoped, revocable credentials** here — e.g. a session token you
  can invalidate, never a long-lived root credential.
- **The model API key never enters the cage.** It stays in the LiteLLM proxy on
  the host; the cage only ever sees the proxy's base URL and a local proxy key.
- **Keep your primary git identity out.** Push host-side, or supply a
  fine-grained, single-repo, revocable PAT — not your account-wide SSH key or a
  broad GitHub token.

The existing `~/.claude` mount stays **read-only**, so the agent can read your
settings/hooks but cannot modify them or exfiltrate keys through them.

## Forking and Customizing

This is designed to be forked. Make it your own.

**Adding dependencies**: Edit the `Dockerfile` to add tools you need. Use Claude Code to help:

```
Add playwright and ffmpeg to the Dockerfile
```

## License

MIT
