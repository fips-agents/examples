# Building AI Agents for OpenShift

A hands-on tutorial for building, deploying, and extending AI agents using the [fips-agents](https://github.com/fips-agents) framework.

**[Start the tutorial](https://fips-agents.github.io/examples/)**

## What you'll build

A complete AI agent system deployed on OpenShift:

- An **agent** that solves calculus problems using remote math tools
- An **MCP server** providing calculus tools (integration, differentiation, limits, etc.)
- A **gateway** that proxies OpenAI-compatible requests to the agent
- A **chat UI** for interacting with the agent in a browser

## Prerequisites

- Python 3.11+
- Access to an OpenShift cluster (or [Red Hat Developer Sandbox](https://developers.redhat.com/developer-sandbox))
- `fips-agents` CLI installed (`pipx install fips-agents-cli`)
- `oc` CLI installed
- `helm` CLI installed

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
