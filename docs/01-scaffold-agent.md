# 1. Scaffold Your Agent

We start by creating an agent project using the `fips-agents` CLI. By the end
of this module, you'll understand every file in the project and have the agent
running locally.

!!! info "Have you finished the prerequisites?"
    Make sure you've worked through [0. Before You Begin](00-prerequisites.md)
    — you'll need a cluster, OpenShift AI, an LLM endpoint, the CLI tools,
    and registry access before Module 2.

## Create the project

The `fips-agents create agent` command scaffolds a complete project from the
built-in template. The `--local` flag sets it up for local development.

```bash
fips-agents create agent calculus-agent --local
```

The CLI scaffolds the full project and prints next steps. Once it finishes,
look at what was created:

```bash
cd calculus-agent && ls
```

```
.claude/        AGENTS.md       CLAUDE.md       Containerfile
Makefile        README.md       agent.yaml      chart/
deploy.sh       evals/          prompts/        pyproject.toml
redeploy.sh     rules/          skills/         src/
tests/          tools/
```

## Project structure

| Path | Purpose |
|------|---------|
| `src/agent.py` | Your agent subclass -- most of your work happens here |
| `agent.yaml` | Configuration: model endpoint, tools, prompts, server settings |
| `prompts/system.md` | System prompt with YAML frontmatter and Markdown body |
| `tools/` | Local tool implementations, one `@tool`-decorated file per tool |
| `skills/` | Progressive-disclosure capabilities (agentskills.io spec) |
| `rules/` | Behavioral constraints, one Markdown file per rule |
| `chart/` | Helm chart for deploying to OpenShift |
| `evals/` | Test scenarios and eval runner |
| `Containerfile` | Multi-stage build using Red Hat UBI base images |
| `Makefile` | Development and deployment commands |
| `AGENTS.md` | Open standard agent descriptor |
| `pyproject.toml` | Python package metadata and dependencies |

## Understanding agent.yaml

This is the central configuration file. It has clearly labeled sections -- here
are the key ones.

### Agent identity

```yaml
agent:
  name: ${AGENT_NAME:-my-agent}
  description: "A brief description of what this agent does"
  version: 0.1.0
```

The name and description appear in logs and on the `/v1/agent-info` endpoint.
We'll change these to match our calculus agent in Module 2.

### Model configuration

```yaml
model:
  endpoint: ${MODEL_ENDPOINT:-http://llamastack:8321/v1}
  name: ${MODEL_NAME:-meta-llama/Llama-3.3-70B-Instruct}
  temperature: 0.7
  max_tokens: 4096
```

This points at any OpenAI-compatible API -- vLLM, LlamaStack, llm-d, or even
OpenAI itself.

!!! tip "Environment variable substitution"
    `${MODEL_ENDPOINT:-http://llamastack:8321/v1}` means: use the
    `MODEL_ENDPOINT` env var if set, otherwise fall back to
    `http://llamastack:8321/v1`. This pattern appears throughout
    `agent.yaml`. It lets a single config file work unchanged across local
    development, staging, and production -- you only override what differs
    via ConfigMaps or Secrets in OpenShift.

### MCP servers

```yaml
mcp_servers: []
```

Empty by default. In Module 4, we'll add our calculus MCP server here. Each
entry can use HTTP or stdio transport:

```yaml
mcp_servers:
  - url: http://mcp-server:8080/mcp/      # HTTP
  - command: /path/to/server             # stdio
    args: [--verbose]
```

### Platform mode (optional, off by default)

```yaml
platform:
  enabled: ${PLATFORM_MODE:-false}
  endpoint: ${OGX_ENDPOINT:-}
```

Off by default. When enabled, the agent delegates LLM orchestration to
[OGX](https://ogx-ai.github.io/) — including MCP tool calls, shield
enforcement, and the inference loop — instead of running them client-side.
We cover this in [Module 10](10-guardrails-and-observability.md); leave it
off until then.

### Local tools and server

```yaml
tools:
  local_dir: ./tools
  visibility_default: agent_only

server:
  host: ${HOST:-0.0.0.0}
  port: ${PORT:-8080}
```

Tools are auto-discovered from `tools/` at startup. The `visibility_default`
controls which tool plane a tool belongs to if it doesn't declare one
explicitly (more on planes below). The server section configures the HTTP
binding -- the agent exposes an OpenAI-compatible `/v1/chat/completions`
endpoint that the gateway and UI communicate through.

## Understanding src/agent.py

The template gives you a `MyAgent` class with the minimal shape — one model
call, optional tool dispatch, return:

```python
from fipsagents.baseagent import BaseAgent, StepResult

class MyAgent(BaseAgent):
    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(result=response.content)
```

Three things to notice:

**BaseAgent subclass.** Your agent inherits from `BaseAgent`, which handles
configuration, tool registration, MCP connections, prompt loading, and
lifecycle management. You implement `step()`.

**The `step()` method.** Called in a loop -- each invocation is one turn of
reasoning. `call_model()` sends the conversation to the LLM with all
registered tool schemas. `run_tool_calls()` executes any tool calls the LLM
requested and re-calls the model until no more tool calls remain.

**Richer calling patterns** are documented in the project's `CLAUDE.md` ("Calling Patterns"): structured output via `call_model_json`, validation-with-retry via `call_model_validated`, and agent-code tool dispatch via `self.use_tool()`. The minimal `step()` above is enough for the rest of this tutorial.

**The `__main__` block.** Starts the agent as an HTTP server:

```python
if __name__ == "__main__":
    from fipsagents.baseagent import load_config
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=MyAgent,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )
    server.run(host=config.server.host, port=config.server.port)
```

Each incoming request creates a fresh agent instance, runs
`setup()` then the `step()` loop then `shutdown()`, and streams the response.
The server also provides `/healthz` for liveness probes and `/v1/agent-info`
for metadata.

## Understanding prompts/system.md

The system prompt uses **Markdown with YAML frontmatter**:

```markdown
---
name: system
description: System prompt for the agent
temperature: 0.3
variables:
  - name: role
    type: string
    description: One-line role description used to focus the agent
    default: "a helpful assistant"
---

You are {role}.

## Instructions

1. Use the tools available to you to accomplish the user's request.
2. If the request is ambiguous, ask a clarifying question before acting.
3. If you cannot complete the request, say so explicitly rather than
   speculating.
```

The frontmatter declares metadata and template variables. Variables use
`{variable_name}` syntax and are substituted when loaded. We'll replace this
generic prompt with one tailored to the calculus domain in Module 4.

The `prompts.system` field in `agent.yaml` designates which prompt file
becomes the system prompt (defaults to `system`, which loads
`prompts/system.md`). At startup, `build_system_prompt()` loads this file,
appends all rules from `rules/`, and appends the skill manifest from
`skills/`.

## The tool system

BaseAgent uses a **two-plane** model for tools:

| Plane | Visibility | Who calls it | Example |
|-------|-----------|-------------|---------|
| Plane 1 | `agent_only` | Your Python code via `self.use_tool()` | Formatting, validation, internal logic |
| Plane 2 | `llm_only` | The LLM via tool-calling protocol | Web search, code execution, MCP tools |

There's also `both` for tools callable from either side, but it's rare.

The template includes examples of each. Here's the plane 2 tool
(`tools/web_search.py`):

```python
from fipsagents.baseagent.tools import tool

@tool(
    description="Search the web for information on a topic",
    visibility="llm_only",
)
async def web_search(query: str) -> str:
    """Search the web and return relevant results.

    Args:
        query: The search query string.
    """
    # ... implementation ...
```

And the plane 1 tool (`tools/format_citations.py`):

```python
@tool(
    description="Format raw URLs and titles into clean citation strings",
    visibility="agent_only",
)
def format_citations(urls: list, titles: list) -> str:
    """Format URLs and titles into numbered citation lines.

    Args:
        urls: List of source URLs.
        titles: List of source titles (same length as urls).
    """
    # ... implementation ...
```

Because `format_citations` uses `visibility="agent_only"`, it is only callable from your Python code via `self.use_tool()`. It does not appear in the LLM's tool schema and is not included in the `/v1/agent-info` tool list.

Key conventions:

- One file per tool in `tools/`. Files starting with `_` are skipped.
- Type hints are mandatory -- the registry builds JSON schemas from them.
- Google-style `Args:` docstrings become per-parameter descriptions.
- Use `async def` for I/O. Sync functions run in a thread executor.

!!! note "MCP tools are always plane 2"
    Tools discovered from MCP servers are automatically registered with
    `llm_only` visibility, regardless of the `visibility_default` setting.
    The LLM decides when to call them, just like local plane 2 tools.

## Run it locally

Install dependencies and start the agent:

```bash
make install
make run-local
```

`make install` creates a virtual environment in `.venv/` and installs
`fipsagents` plus your project's dependencies. `make run-local` starts the
HTTP server on port 8080.

Once you see `Uvicorn running on http://0.0.0.0:8080`, test it:

```bash
curl localhost:8080/healthz
```

```json
{"status": "ok"}
```

```bash
curl localhost:8080/v1/agent-info | python -m json.tool
```

```json
{
    "agent": {
        "name": "my-agent",
        "description": "A brief description of what this agent does",
        "version": "0.1.0"
    },
    "model": {
        "name": "meta-llama/Llama-3.3-70B-Instruct",
        "temperature": 0.7,
        "max_tokens": 4096
    },
    "system_prompt": "You are a helpful assistant.\n\n## Instructions\n...",
    "tools": []
}
```

The `tools` array is a list of objects (`{name, description, parameters}`)
when tools are registered, and `system_prompt` reflects the rendered prompt
text after rule and skill injection.

!!! note "MemoryHub log line"
    On first start you'll see `MemoryHub config at .memoryhub.yaml has no
    server_url — memory disabled (set server_url to enable).` That's expected
    — the scaffold ships a stub `.memoryhub.yaml`, and the agent falls back
    to `NullMemoryClient` cleanly. See `/add-memory` for wiring up real
    memory later.

Stop the server with `Ctrl+C`.

## What's next

The scaffolded project runs but is still generic. In
[Module 2](02-configure-and-deploy.md), you'll customize the configuration,
point it at a real LLM on your OpenShift cluster, and deploy it.
