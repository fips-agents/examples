# Building AI Agents on Red Hat AI

A hands-on tutorial that takes you from zero to a deployed AI agent system
on **Red Hat AI**, using the [fips-agents](https://github.com/fips-agents)
toolkit.

This tutorial was last verified against **fipsagents v0.11.0** (April 2026). The current release is **v0.26.0** (May 2026) — see [What's New Since v0.11](#whats-new-since-v011) for features available in newer versions.

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
                              vLLM (gpt-oss-20b)
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
    OpenShift cluster with OpenShift AI and a GPU serving `gpt-oss-20b`
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
| [10. Platform Mode and Guardrails](10-guardrails-and-observability.md) | Graduate tool orchestration, shields, and tracing to OGX server-side. Requires fipsagents 0.21+ |
| [11. Scaling with llm-d](11-scaling-with-llm-d.md) | Conceptual: disaggregated prefill/decode + KV-cache routing behind OGX |

### Supplementary modules

These standalone modules extend the tutorial with RHOAI 3.4 platform features.
They are independent of each other and can be completed in any order after the
prerequisites listed in each module.

| Module | What you'll do |
|--------|----------------|
| [Agent Memory with MemoryHub](supplementary/agent-memory.md) | Add cross-session memory via MemoryHub's MCP-based semantic store |
| [Models as a Service](supplementary/maas-model-serving.md) | Deploy MaaS: subscription-based model governance, API key auth, token quotas, usage tracking (RHOAI 3.4+) |
| [MCP Gateway](supplementary/mcp-gateway.md) | Deploy MCP Gateway: centralized tool access, auth, rate limiting across MCP servers (RHOAI 3.4+, Tech Preview) |

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

## What's new since v0.11

The tutorial's module sequence is stable at v0.11.0. Newer fipsagents releases add capabilities that slot into the same architecture without changing Modules 1–9. To use these, bump the version in your agent's `pyproject.toml` and consult `docs/architecture.md` in the [agent-template](https://github.com/fips-agents/agent-template) repo.

| Version | Feature | What it adds |
|---------|---------|-------------|
| 0.20.0 | Image input | Multimodal message support in `astep_stream()` |
| 0.21.0 | Platform mode | Delegate LLM orchestration to OGX server-side (Module 10 covers this) |
| 0.22.0 | Subagent-as-tool | Register peer agents in `agent.yaml`, auto-get a `delegate_to_agent` tool |
| 0.22.0 | Question tool | Structured questions from agent to operator with `ask_user` |
| 0.23.0 | Session compaction | LLM-driven summarization of old messages on context overflow |
| 0.23.0 | Doom-loop detection | Breaks stuck tool-call loops automatically |
| 0.23.0 | Per-tool permissions | Allow/deny/ask gates on individual tool calls |
| 0.24.0 | Event-triggered mode | React to webhooks, cron, Kafka, Redis — not just chat |
| 0.24.0 | Session fork & revert | Branch conversation history for exploration |
| 0.24.0 | OTEL trace fidelity | Configurable detail levels for trace replay |
| 0.25.0 | Kafka/Redis sources | Event-triggered agents can consume Kafka topics and Redis Streams |
| 0.26.0 | State recovery | Reducer-based checkpoint/replay for long-running agents |

The `calculus-coordinator/` directory in this repo demonstrates subagent-as-tool (v0.22.0).
