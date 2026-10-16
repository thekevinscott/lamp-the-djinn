"""Provider env injection: wiring whatever runs *inside* the cage to the proxy.

A "harness" is the agent program executed in the sandboxed devcontainer (Claude
Code, Codex, Aider, or any arbitrary command the user types). lamp-the-djinn is
harness-agnostic: it does not maintain a registry of known agents. The command
is whatever the user passes through on the CLI; this module's only job is to
hand that command the env vars it needs to reach the LiteLLM proxy on the host.

Provider seam
-------------
Every harness talks to ONE local endpoint -- the LiteLLM proxy -- never to a
provider directly. The proxy abstracts away *which* backend serves a request:
``--model local`` may hit llama.cpp on a local box, while ``--model glm-5.2``
fans out to OpenRouter. The harness neither knows nor cares; it only sees a
base URL and an API key.

Because the command is arbitrary, we cannot know in advance whether it speaks
the OpenAI chat-completions wire format or the Anthropic Messages format. So we
inject BOTH provider families and let the harness pick up whichever it reads:

* OpenAI family (Codex, Aider, custom): ``OPENAI_BASE_URL``, ``OPENAI_API_KEY``,
  ``OPENAI_MODEL`` -- pointed at the proxy's ``/v1`` (OpenAI-format) endpoint.
* Anthropic family (Claude Code): ``ANTHROPIC_BASE_URL``,
  ``ANTHROPIC_AUTH_TOKEN``, ``ANTHROPIC_MODEL``.

NOTE on ``ANTHROPIC_BASE_URL``: Claude Code's native ``/v1/messages`` calls
speak the Anthropic Messages format, which LiteLLM exposes on its
*anthropic-format* passthrough endpoint. That endpoint may live at a DIFFERENT
path than the ``/v1`` OpenAI-compatible one: the Anthropic SDK appends
``/v1/messages`` itself, so ``ANTHROPIC_BASE_URL`` is the proxy URL with any
trailing ``/v1`` dropped.
"""

from __future__ import annotations


def provider_env_all(proxy_url: str, model: str, api_key: str) -> dict[str, str]:
    """Build env vars wiring an arbitrary harness at the LiteLLM proxy.

    Returns BOTH provider families pointing at the proxy, so the same env works
    whether the command speaks the OpenAI or the Anthropic wire format. The
    proxy abstracts local-llama-vs-OpenRouter behind one endpoint, so the same
    three knobs (base URL, key, model) configure every backend.

    The Anthropic base URL drops a trailing ``/v1`` (see module docstring).
    """
    anthropic_url = proxy_url.removesuffix("/v1")
    return {
        "OPENAI_BASE_URL": proxy_url,
        "OPENAI_API_KEY": api_key,
        "OPENAI_MODEL": model,
        "ANTHROPIC_BASE_URL": anthropic_url,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_MODEL": model,
    }
