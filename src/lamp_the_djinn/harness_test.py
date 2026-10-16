"""Unit tests for provider env injection (the provider seam).

Colocated with harness.py: these pin the pure mapping from (proxy_url, model,
key) to the OpenAI/Anthropic env families the cage hands an arbitrary harness.
No proxy is contacted; the function is pure string assembly plus one env read.
"""

from unittest import mock

import pytest

from lamp_the_djinn.harness import provider_env_all

pytestmark = pytest.mark.unit


def describe_provider_env_all():
    """Both provider families are emitted, pointed at the proxy."""

    def it_emits_both_families():
        env = provider_env_all("http://host.docker.internal:4000/v1", "glm-5.2", "k")
        assert env["OPENAI_BASE_URL"] == "http://host.docker.internal:4000/v1"
        assert env["OPENAI_API_KEY"] == "k"
        assert env["OPENAI_MODEL"] == "glm-5.2"
        assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:4000"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "k"
        assert env["ANTHROPIC_MODEL"] == "glm-5.2"

    def it_points_anthropic_at_the_proxy_root():
        """The Anthropic SDK appends /v1/messages itself, so a trailing /v1 is dropped."""
        assert provider_env_all("http://h:4000/v1", "local", "k")["ANTHROPIC_BASE_URL"] == "http://h:4000"
        assert provider_env_all("http://h:4000/x", "local", "k")["ANTHROPIC_BASE_URL"] == "http://h:4000/x"

    def it_ignores_the_ltd_anthropic_proxy_url_variable():
        with mock.patch.dict("os.environ", {"LTD_ANTHROPIC_PROXY_URL": "http://h:4000/anthropic"}):
            env = provider_env_all("http://h:4000/v1", "local", "k")
        assert env["ANTHROPIC_BASE_URL"] == "http://h:4000"
