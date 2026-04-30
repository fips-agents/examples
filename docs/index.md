# Building AI Agents on Red Hat AI

A hands-on tutorial that takes you from zero to a deployed AI agent system
on **Red Hat AI**, using the [fips-agents](https://github.com/fips-agents)
framework.

This tutorial was last verified against **fipsagents v0.11.0** (April 2026).

## What is Red Hat AI?

Red Hat AI is Red Hat's portfolio for building and running AI on the hybrid
cloud. In this tutorial, "Red Hat AI" specifically means **OpenShift AI
running on OpenShift**: OpenShift is the underlying Kubernetes platform,
OpenShift AI is the MLOps layer that manages model serving (via KServe and
vLLM), and your agents run as ordinary OpenShift workloads alongside.

## What you'll build

By the end of this tutorial, you'll have a complete system running on Red
Hat AI:

```
Browser → Chat UI → Gateway → Agent → MCP Server (calculus tools)
                                  ↓
                              vLLM (Gemma 4 9B)
```

- A **Calculus Helper agent** that solves math problems using remote tools
- A **calculus MCP server** with 8 SymPy-powered tools (integration, differentiation, limits, etc.)
- An **HTTP gateway** that proxies OpenAI-compatible API requests
- A **chat UI** for browser-based interaction

## Prerequisites

The full prerequisite checklist — cluster, OpenShift AI, LLM serving, CLI
tools, and registry access — is its own module:

→ **[0. Before You Begin](00-prerequisites.md)**

!!! tip "Two paths"
    The tutorial supports two paths. **Path A** is the full experience: an
    OpenShift cluster with OpenShift AI and a GPU serving Gemma 4 9B
    via vLLM. **Path B** is for students without GPU access (Developer
    Sandbox, CRC, or any cluster without a GPU node) — you supply an
    external OpenAI-compatible model URL and deploy everything else on
    your cluster. Both paths are documented in
    [Before You Begin](00-prerequisites.md).

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
| [9. File Uploads](09-file-uploads.md) | Drag-drop uploads, Docling parsing, MIME validation, ClamAV scanning |

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
