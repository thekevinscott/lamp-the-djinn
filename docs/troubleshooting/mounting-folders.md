# Mounting additional folders

How `-v` paths map into the cage, and the failure modes worth knowing.

## Where a `-v` path lands

`-v` (repeatable) takes three forms:

| You pass | Cage sees | Why |
| --- | --- | --- |
| `-v ~/.pi/agent/models.json` | `/home/node/.pi/agent/models.json` | A path under your home maps to the **cage user's** home — the cage runs as `node`, not as you, so a path-identity mount of a home path would land where the harness never looks. |
| `-v /mnt/data` | `/mnt/data` | A path outside your home keeps path identity, so absolute paths the agent emits stay valid on the host. |
| `-v /host/dir:/elsewhere` | `/elsewhere` | An explicit `HOST:CONTAINER` mapping is honored as-is. |

Mounts are **read-write** by default. For read-only, use the explicit form
with Docker's suffix: `-v /host/dir:/container/dir:ro`.

## "Permission denied" (EACCES) writing next to a mounted file

Mounting a **single file** under your home — the right way to hand a harness
just its config — makes Docker create the file's parent directories inside the
cage owned by **root**. A harness that writes *next to* the file (pi creating
`~/.pi/agent/sessions/`) then dies with `EACCES`.

ltd fixes this from the host: once the cage is up, it re-owns those
auto-created parent directories to the cage user. If you still hit this on an
old version, **upgrade ltd** — and never work around it by adding in-cage
`sudo chown` (the cage deliberately has no general root primitive).

## Docker created a directory where my file should be

If the host path doesn't exist when the cage starts, Docker creates it as a
**root-owned directory** — so `-v ~/.pi/agent/models.json` with no such file
yields a directory named `models.json` in the cage. Create the file on the
host first:

```bash
mkdir -p ~/.pi/agent && touch ~/.pi/agent/models.json
```

## "Read-only file system" (EROFS)

Some mounts are read-only **by design** and writing to them fails with EROFS:

- The firewall allowlist files (machine-local and `--allow-domains-file`) —
  the agent must never widen its own egress.
- SSH keys and `~/.gnupg` (when `--ssh-key-file` / `--gpg-key-id` are used).
- In strict mode, the staged `~/.claude` **config** copy is writable but
  discarded on exit; only transcripts (`projects/`, `history.jsonl`) write
  through to the host.

If a package manager (`npm`, `uvx`) fails with EROFS against a cache, you're
pointing it at a read-only mount. Untrusted runs intentionally use an
ephemeral in-container cache; the writable shared cache is `--trusted` only.

## Scope mounts tightly

**Everything mounted into the cage is readable by the untrusted agent.** Mount
the single file a harness needs, not its whole config directory — e.g.
`~/.pi/agent/models.json`, not `~/.pi` (which also holds `auth.json`, your pi
credentials). When a harness needs more, prefer read-only explicit mounts.

## Related

- [Deep Dive](../deep-dive) — trust tiers and credential persistence.
- [GPG signing](./gpg-signing) — the read-only `~/.gnupg` mount.
