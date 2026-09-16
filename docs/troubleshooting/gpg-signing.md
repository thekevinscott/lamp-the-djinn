# GPG signing

How signed commits work in the cage, and what to check when they don't.

## How it's wired

Passing `--gpg-key-id YOUR_KEY_ID` (or setting `LTD_GPG_KEY_ID`) does three
things at cage startup:

1. Copies your host `~/.gnupg` into this run's cache dir and mounts **that
   copy**, read-write, at `/home/node/.gnupg`. Your host keyring is never
   mounted and never written by the cage; the copy is discarded with the rest
   of the per-run cache on exit.
2. Sets `user.signingkey`, `commit.gpgsign=true`, and `gpg.program=gpg` in the
   cage's git config.
3. Starts `gpg-agent`.

The copy exists because gpg-agent creates sockets and lockfiles *inside*
`GNUPGHOME`: mounting the host keyring read-only leaves the agent unable to
start, and mounting it read-write would let the agent tamper with your real
keys. A disposable copy gives a working agent and an untouched host keyring.

Without the flag there is no keyring mount and no signing config — commits are
unsigned by default.

## Commits aren't signed at all

You didn't pass `--gpg-key-id` (or set `LTD_GPG_KEY_ID`). Signing is opt-in;
re-run with the flag.

## "No secret key" in the cage

The key must exist in your **host** keyring — the cage only sees a copy of it,
taken when the cage starts. On the host:

```bash
gpg --list-secret-keys --keyid-format long
# sec   ed25519/C567F8478F289CC4 ...   <- pass the part after the slash:
ltd --gpg-key-id C567F8478F289CC4 ...
```

Keys you generate or import *inside* the cage vanish with it — the keyring there
is a disposable copy. Create keys on the host, then restart the cage.

## gpg can't start at all: "Read-only file system"

```
gpg: failed to create temporary file '/home/.../.gnupg/.#lk0x...': Read-only file system
gpg: can't connect to the gpg-agent: Read-only file system
gpg: signing failed: No agent running
```

gpg-agent needs to create sockets and lockfiles **inside `GNUPGHOME`**, so it
cannot start when `~/.gnupg` is itself read-only. The key material is fine; the
agent just has nowhere to write.

**This no longer happens inside the ltd cage** — ltd stages a writable copy of
the keyring for you (see *How it's wired*). If you see it there, you're on a
version predating that change; upgrade.

It still happens on hosts with a read-only keyring at the environment level: a
snapshot-mounted home, a read-only CI image, a container someone else built.
On a machine **you** control, the fix is to give gpg a writable **copy** of the
keyring and point git at a wrapper that selects it:

```bash
# 1. Copy the keyring somewhere writable
cp -r ~/.gnupg ~/.gnupg-rw
chmod 700 ~/.gnupg-rw

# 2. A wrapper that swaps GNUPGHOME before invoking the real gpg
cat > ~/.gpg-wrapper.sh <<'EOF'
#!/bin/sh
export GNUPGHOME="$HOME/.gnupg-rw"
exec gpg "$@"
EOF
chmod +x ~/.gpg-wrapper.sh

# 3. Tell git to sign through the wrapper (repo-local is enough)
git config --local gpg.program "$HOME/.gpg-wrapper.sh"
```

Commits then sign normally — gpg-agent runs against the writable copy.

**Caveat: the copy goes stale.** New keys, revocations, and expiry changes
made against the original `~/.gnupg` won't appear in `~/.gnupg-rw`; re-copy
whenever the original changes. (ltd's own copy avoids this by being taken fresh
at every cage start.)

## Signing fails: pinentry / passphrase errors

`signing failed: Inappropriate ioctl for device`, `No pinentry`, or a hang on
commit all mean gpg tried to prompt for a passphrase and couldn't — the agent
runs non-interactively, so there is no terminal to prompt on.

The practical fix: **use a passphrase-free key for your bot identity.** A
prompting key will block an autonomous agent on every commit. (The cage does
set `GPG_TTY`, which fixes this for interactive shells, but not for an agent
running without a TTY.)

## Commits are signed but GitHub shows "Unverified"

- The **public** key must be uploaded to the GitHub account that owns the
  identity: `gpg --armor --export YOUR_KEY_ID`, then add it under
  Settings → SSH and GPG keys.
- The `--git-user-email` you pass must match an email on that key/account.

## Verify it's working

Inside the cage:

```bash
git log --show-signature -1   # expect "Good signature from ..."
```

## Security note

Everything mounted into the cage is readable — and the staged keyring copy is
*usable* — by the untrusted agent. Signing inside the cage necessarily means the
private key material is readable there; the copy only guarantees the agent can't
reach back into your host keyring. Use a **dedicated bot keypair**, not your
personal key, so revocation is cheap if the agent misbehaves. Combine with
`--git-user-name yourbot` / `--git-user-email yourbot@...` so agent commits are
distinguishable from yours.
