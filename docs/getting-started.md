# Getting Started

By the end of this page you'll have run a coding agent inside the cage: full
autonomy for the agent, no risk to the rest of your system.

## Prerequisites

- **Docker** installed, running, and accessible by your user
  (`docker info` succeeds).
- **uv** (for `uvx`) — <https://docs.astral.sh/uv/>. `pipx` works too.

## Run it

From the project directory you want the agent to work in:

```bash
uvx --from git+https://github.com/thekevinbot/lamp-the-djinn lamp-the-djinn
```

The first run pulls the container image (or builds it locally if the pull
fails), starts the cage, configures the firewall, and drops you into Claude
Code with `--dangerously-skip-permissions` — inside the cage, that's safe.

`ltd` is the short alias; both entry points are the same program.

## Run a different agent

Everything after ltd's own options is the command that runs in the cage,
passed through untouched:

```bash
ltd claude -p "fix the bug"   # the -p goes to claude, not ltd
ltd npx @anthropic/claude     # an agent straight from npm
ltd aider                     # any harness on PATH
ltd pi -c                     # harness flags pass through
ltd --safe-mode               # bare claude with permission prompts on
```

## What just happened

- Your project directory — and nothing else — was mounted into the cage, at
  its real host path.
- A default-deny egress firewall came up: only allowlisted domains are
  reachable from inside.
- The agent ran as an unprivileged user with no access to your credentials.
- When the command exited, the cage was destroyed. The diff it left in your
  project is yours to keep or `git reset --hard` away.

## Next steps

- [Deep Dive](./deep-dive) — the two seams (isolation, provider), the trust
  model, and how credentials stay out of the cage.
- [Troubleshooting](./troubleshooting/) — GPG signing and mounting extra
  folders.
- [Dedicated GitHub identity](https://github.com/thekevinbot/lamp-the-djinn#configuration)
  — recommended, to distinguish agent commits from your own.
