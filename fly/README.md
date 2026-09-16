# `fly` isolation backend (remote Firecracker microVM)

This directory is the **`fly`** isolation backend for lamp-the-djinn. Instead of
running the cage as a local Docker container on a shared host, it runs the cage
as a remote [Fly.io](https://fly.io) Machine. Every Fly Machine boots inside a
[Firecracker](https://firecracker-microvm.github.io/) microVM, giving the
untrusted agent a hardware-virtualization boundary (its own kernel) rather than a
shared host kernel behind `runc` namespaces.

This sits alongside the local runtime seam (`--runtime` / `LTD_RUNTIME`, which
selects `runc` vs gVisor's `runsc` vs `kata-runtime` for the *local* backend).
The `fly` backend is the "run it somewhere else entirely" end of that spectrum.

> **UNVERIFIED scaffolding.** There is no Fly account or `flyctl` available in
> the environment this was authored in, so none of the files here have been
> deployed, launched, or otherwise validated. Treat every command below as a
> starting point to verify, not a known-good recipe.

## Files

| File            | Purpose                                                              |
| --------------- | ------------------------------------------------------------------- |
| `fly.toml`      | Fly app config: app name, image, scale-to-zero, env/secret hints.   |
| `entrypoint.sh` | Boot script: brings Tailscale up (guarded), then execs the cage.    |
| `README.md`     | This file.                                                          |

## How it reaches the local model and honors egress

The whole point of the local backend is that the agent talks to a LiteLLM proxy
on `tower` (your machine) and is held to a strict egress allowlist. A remote
microVM on Fly is not on your LAN, so it cannot reach `tower` directly.

[Tailscale](https://tailscale.com) closes that gap. `entrypoint.sh` starts
`tailscaled` and runs `tailscale up --authkey=$TS_AUTHKEY` at boot, which joins
the cage to your tailnet. Once joined:

- the cage can reach the proxy at its tailnet address (e.g. `http://tower:4000/v1`,
  set via `LTD_PROXY_URL`), so the agent uses your local model exactly as it does
  in the local backend; and
- the same egress tightening applies -- set `LTD_EGRESS_PROXY_ONLY=1` and
  `LTD_PROXY_HOST=<tower's tailnet IP>` so the cage's firewall only permits
  egress to the proxy host (see `../.devcontainer/init-firewall.sh`).

`TS_AUTHKEY` is a secret. Set it with `fly secrets`, never in `fly.toml`:

```sh
fly secrets set TS_AUTHKEY=tskey-auth-xxxxxxxxxxxx
```

## Launch / deploy

From this directory:

```sh
# One-time: create the app from fly.toml (review the prompts; do NOT let it
# overwrite the committed fly.toml unless you mean to).
fly launch --copy-config --no-deploy

# Set secrets (auth key for Tailscale, proxy key if your proxy requires one).
fly secrets set TS_AUTHKEY=tskey-auth-xxxxxxxxxxxx
fly secrets set LTD_PROXY_API_KEY=...           # only if the proxy enforces auth

# Deploy the cage image.
fly deploy

# Open a shell in the running cage.
fly ssh console
```

The app is configured to **scale to zero** (`min_machines_running = 0`,
`auto_stop_machines = "stop"`), so an idle cage costs nothing and a new request
(or `fly machine start`) wakes it.

## What still needs verifying

- Whether the published cage image (`ghcr.io/thekevinscott/lamp-the-djinn:latest`)
  actually contains `tailscaled`/`tailscale`; if not, add them to the image or
  bake a Fly-specific Dockerfile.
- Whether userspace-networking Tailscale is sufficient for the agent's traffic,
  or whether the microVM can be given a TUN device for normal routing.
- That `LTD_PROXY_URL` over the tailnet resolves and connects from inside the
  microVM, and that the egress firewall (`LTD_EGRESS_PROXY_ONLY`) behaves as
  intended there -- the firewall needs `NET_ADMIN`, which must be confirmed in
  the Fly Machine.
