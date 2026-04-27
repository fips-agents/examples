# Building AI Agents for OpenShift

A hands-on tutorial that takes you from zero to a deployed AI agent system
on Red Hat OpenShift, using the [fips-agents](https://github.com/fips-agents)
framework.

This tutorial was last verified against **fipsagents v0.11.0** (April 2026).

## What you'll build

By the end of this tutorial, you'll have a complete system running on OpenShift:

```
Browser → Chat UI → Gateway → Agent → MCP Server (calculus tools)
                                  ↓
                              LLM (vLLM)
```

- A **Calculus Helper agent** that solves math problems using remote tools
- A **calculus MCP server** with 8 SymPy-powered tools (integration, differentiation, limits, etc.)
- An **HTTP gateway** that proxies OpenAI-compatible API requests
- A **chat UI** for browser-based interaction

## Prerequisites

!!! info "What you need"
    - Python 3.11 or later
    - Access to an OpenShift cluster with a deployed LLM (vLLM or LlamaStack)
    - `fips-agents` CLI: `pipx install fips-agents-cli`
    - `oc` CLI: [Install from Red Hat](https://mirror.openshift.com/pub/openshift-v4/clients/ocp/)
    - `helm` CLI: [Install from Helm](https://helm.sh/docs/intro/install/)
    - A terminal and a text editor

## Modules

| Module | What you'll do |
|--------|----------------|
| [1. Scaffold Your Agent](01-scaffold-agent.md) | Create an agent project, explore every file |
| [2. Configure and Deploy](02-configure-and-deploy.md) | Edit config, deploy to OpenShift, verify |
| [3. Build an MCP Server](03-build-mcp-server.md) | Create a calculus tool server from scratch |
| [4. Wire MCP to Agent](04-wire-mcp-to-agent.md) | Connect the tools, update the prompt |
| [5. Gateway and UI](05-gateway-and-ui.md) | Deploy the full stack, test end-to-end |
| [6. Code Execution Sandbox](06-code-sandbox.md) | Deploy a sandbox, give the agent code execution |
| [7. Extend with AI](07-extend-with-ai.md) | Use AI-assisted slash commands to add capabilities |
| [8. Production Hardening](08-secrets-and-production.md) | Secrets, FIPS, scaling, observability (metrics, traces, sessions, user feedback) |

## Reference

Deep-dive pages linked from the tutorial:

- [agent.yaml Reference](reference/agent-yaml.md) -- every config section explained
- [Helm Chart Anatomy](reference/helm-chart.md) -- what the chart produces
- [Makefile Targets](reference/makefile.md) -- all available commands
- [BaseAgent API](reference/baseagent-api.md) -- key methods
- [MCP Protocol](reference/mcp-protocol.md) -- tools, prompts, resources

## How to follow along

Each module builds on the previous one. You'll run real commands, edit real
files, and deploy real services. The completed code is in this repository if
you get stuck:

- `calculus-agent/` -- the finished agent
- `calculus-helper/` -- the finished MCP server
