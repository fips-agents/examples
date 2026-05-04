# Building AI Agents on Red Hat AI

A hands-on tutorial for building, deploying, and extending AI agents on **Red Hat AI** (OpenShift AI on OpenShift) using the [fips-agents](https://github.com/fips-agents) toolkit.

**[Start the tutorial](https://fips-agents.github.io/examples/)**

## What you'll build

A complete AI agent system deployed on Red Hat AI:

- An **agent** that solves calculus problems using remote math tools
- An **MCP server** providing calculus tools (integration, differentiation, limits, etc.)
- A **gateway** that proxies OpenAI-compatible requests to the agent
- A **chat UI** for interacting with the agent in a browser

## Prerequisites

The full checklist (cluster, OpenShift AI, LLM serving, CLI tools, registry) lives in the [**Before You Begin**](https://fips-agents.github.io/examples/00-prerequisites/) module.

The tutorial supports two paths:

- **Path A** — OpenShift cluster with OpenShift AI and a GPU serving Granite 3.3 8B Instruct on vLLM (the full experience).
- **Path B** — no cluster GPU? Use the [Developer Sandbox](https://developers.redhat.com/developer-sandbox) or any cluster, and point the agent at an external OpenAI-compatible model URL.

## Example projects

| Directory | Description |
|-----------|-------------|
| `calculus-agent/` | Complete agent configured for MCP-based calculus tools |
| `calculus-helper/` | FastMCP server with 8 SymPy-powered calculus tools |

## Local development

```bash
pip install mkdocs-material
mkdocs serve
```

Then open http://localhost:8000 to preview the tutorial.
