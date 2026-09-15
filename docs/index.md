---
layout: home

hero:
  name: lamp-the-djinn
  text: Full autonomy for any coding agent, none of the risk.
  tagline: The agent gets free rein inside a disposable cage. Your files, credentials, and network stay out of reach.
  actions:
    - theme: brand
      text: Getting Started
      link: /getting-started
    - theme: alt
      text: Deep Dive
      link: /deep-dive
    - theme: alt
      text: Troubleshooting
      link: /troubleshooting/

features:
  - title: Runs anything
    details: claude, aider, pi, or any command you pass — harness- and model-agnostic by design. One LiteLLM proxy fronts your models, so real API keys never enter the cage.
  - title: Touches only your project
    details: A Docker cage mounts just the project directory, at its real path. Everything else on your machine is unreachable; the cage is destroyed on exit.
  - title: Default-deny network
    details: An iptables firewall blocks all outbound traffic except an explicit domain allowlist — the agent can't exfiltrate your code or secrets.
  - title: Git as undo
    details: Review the diff the agent produced, then keep it or git reset --hard it away. The cage is ephemeral; your judgment is the gate.
---
