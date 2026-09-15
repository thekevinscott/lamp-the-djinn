# Use Playwright base image which includes Node.js, Chromium, and all browser dependencies pre-installed.
# PLAYWRIGHT_VERSION is the single source of truth: it tags the base image (which
# bundles the matching browsers under /ms-playwright) AND pins the global
# `playwright` CLI below. Keeping them equal is what stops the drift where a bare
# `npx playwright` pulls a newer playwright whose browser revision isn't bundled.
ARG PLAYWRIGHT_VERSION=1.57.0
FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble

ARG TZ
ENV TZ="$TZ"

ARG CLAUDE_CODE_VERSION=latest

# Install basic development tools and iptables/ipset
# Note: Playwright image is Ubuntu-based, so we use apt-get
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt-get update && apt-get install -y --no-install-recommends \
  less \
  git \
  procps \
  sudo \
  fzf \
  zsh \
  unzip \
  gnupg2 \
  gh \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  aggregate \
  jq \
  nano \
  openssh-client \
  ca-certificates \
  iputils-ping

# Install Docker CLI and git-delta (with retry for transient failures)
ARG DOCKER_VERSION=27.3.1
ARG GIT_DELTA_VERSION=0.18.2
RUN ARCH=$(dpkg --print-architecture) && \
  (curl -fsSL --retry 3 --retry-delay 5 "https://download.docker.com/linux/static/stable/$(uname -m)/docker-${DOCKER_VERSION}.tgz" | tar xz --strip-components=1 -C /usr/local/bin docker/docker) && \
  curl -fsSL --retry 3 --retry-delay 5 "https://github.com/dandavison/delta/releases/download/${GIT_DELTA_VERSION}/git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" -o /tmp/git-delta.deb && \
  dpkg -i /tmp/git-delta.deb && rm /tmp/git-delta.deb

# Install uv/uvx from official image (https://docs.astral.sh/uv/guides/integration/docker/)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install pnpm globally, pinned. NOT via corepack: pnpm 12 renamed its bin to
# bin/pnpm.mjs while corepack 0.34.2 still looks for bin/pnpm.cjs, so
# `corepack prepare pnpm@latest` dies with MODULE_NOT_FOUND. A global install
# also needs no runtime download -- a corepack shim fetching pnpm on first use
# would fail in the cage, where egress is default-deny.
ARG PNPM_VERSION=12.4.2
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
  npm install -g pnpm@${PNPM_VERSION}

# Copy firewall scripts, utilities, GPG setup, and domain whitelist
COPY --chmod=755 init-firewall.sh add-domain-to-firewall.sh safe-rm setup-gpg.sh /usr/local/bin/
COPY whitelisted-domains.txt /usr/local/share/whitelisted-domains.txt

# Install Claude Code globally as root
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
  npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Install the Playwright CLI globally at the SAME version as the base image, so a
# bare `npx playwright` finds this on-PATH binary instead of fetching latest --
# whose browser revision wouldn't match the bundled /ms-playwright browsers.
ARG PLAYWRIGHT_VERSION
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
  npm install -g playwright@${PLAYWRIGHT_VERSION}

# Rename existing UID 1000 user to 'node' for devcontainer compatibility
# The Playwright image may have 'pwuser' or 'ubuntu' user at UID 1000 depending on version
# Also set up command history, workspace, and config directories in one layer
RUN OLD_USER=$(getent passwd 1000 | cut -d: -f1) && \
  OLD_GROUP=$(getent group 1000 | cut -d: -f1) && \
  usermod -l node -d /home/node -m "$OLD_USER" && \
  groupmod -n node "$OLD_GROUP" && \
  chsh -s /bin/zsh node && \
  { echo 'node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh'; \
    echo 'node ALL=(root) NOPASSWD: /usr/local/bin/add-domain-to-firewall.sh'; \
    echo 'node ALL=(root) NOPASSWD: /sbin/ipset add allowed-domains *'; \
    echo 'node ALL=(root) NOPASSWD: /sbin/ipset test allowed-domains *'; \
    echo 'node ALL=(root) NOPASSWD: /sbin/ipset list allowed-domains'; \
  } > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall && \
  (usermod -aG docker node 2>/dev/null || groupadd docker && usermod -aG docker node || true) && \
  mkdir /commandhistory && \
  touch /commandhistory/.bash_history && \
  chown -R node /commandhistory && \
  mkdir -p /workspace /home/node/.claude /home/node/.config && \
  chown -R node:node /workspace /home/node/.claude /home/node

# Set environment variables
ENV DEVCONTAINER=true
ENV SHELL=/bin/zsh
ENV EDITOR=nano
ENV VISUAL=nano

WORKDIR /workspace

# Switch to non-root user for remaining setup
USER node

# Install oh-my-zsh and configure shell
# Pre-seed GitHub SSH host keys to prevent MITM attacks
# Keys from: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended && \
  mkdir -p ~/.ssh && chmod 700 ~/.ssh && \
  echo 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' >> ~/.ssh/known_hosts && \
  echo 'github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=' >> ~/.ssh/known_hosts && \
  echo 'github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=' >> ~/.ssh/known_hosts && \
  chmod 600 ~/.ssh/known_hosts && \
  echo 'plugins=(git fzf)' >> ~/.zshrc && \
  echo 'source /usr/share/doc/fzf/examples/key-bindings.zsh 2>/dev/null || true' >> ~/.zshrc && \
  echo 'source /usr/share/doc/fzf/examples/completion.zsh 2>/dev/null || true' >> ~/.zshrc && \
  echo 'export PROMPT_COMMAND="history -a"' >> ~/.zshrc && \
  echo 'export HISTFILE=/commandhistory/.bash_history' >> ~/.zshrc

# Health check to verify Claude Code is functional
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
  CMD claude --version > /dev/null 2>&1 || exit 1
