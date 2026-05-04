# 4. Wire MCP to Agent

Your calculus MCP server is deployed and serving tools. Now you'll connect it
to the agent you built in Modules 1 and 2. The key insight of this module:
**MCP decouples tool implementation from agent logic.** The agent doesn't know
or care how integration is computed -- it just calls a tool and gets a result.
You'll make three small changes (config, prompt, code) and redeploy.

## What changes and what doesn't

Before diving in, here's the full picture of what you're about to do:

| File | Change | Why |
|------|--------|-----|
| `agent.yaml` | Add `mcp_servers:` entry | Tell the agent where to find the MCP server |
| `prompts/system.md` | Rewrite for calculus domain | Tell the model what it is and what tools it has |
| `src/agent.py` | Rename class for calculus domain | Update identity to match the new purpose |
| `tools/web_search.py` | Delete | No longer needed -- real tools come from MCP |

Everything else -- the Helm chart, the Containerfile, the Makefile, the
fipsagents code -- stays untouched. That's the power of the architecture: swap
tools by changing config, not plumbing.

## Connect the MCP server

Open `agent.yaml` and find the `mcp_servers:` section. In Module 1, it looked
like this:

```yaml
# mcp_servers:
#   - url: ${MCP_SEARCH_URL:-http://search-mcp:8080/mcp}
mcp_servers: []
```

Replace it with a pointer to your deployed calculus-helper server:

```yaml
mcp_servers:
  - url: ${MCP_CALCULUS_URL:-http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/}
```

The URL uses OpenShift's internal service DNS. The service name `mcp-server`
comes from the MCP server's `openshift.yaml` manifest. Since the agent runs
in `calculus-agent` and the MCP server runs in `calculus-mcp`, you need the
fully qualified domain name:

```
http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/
```

The pattern is `<service>.<namespace>.svc.cluster.local:<port><path>`. If you
later deploy both to the same namespace, the short name `http://mcp-server:8080/mcp/`
also works.

!!! tip "Environment variable override"
    The `${MCP_CALCULUS_URL:-...}` pattern means you can override the URL per
    environment without changing `agent.yaml`. In a staging namespace that runs
    its own MCP instance, just set `MCP_CALCULUS_URL` in the ConfigMap.

At startup, BaseAgent connects to every URL listed under `mcp_servers:`,
discovers the available tools, and registers them with `llm_only` visibility.
The LLM sees them alongside any local tools -- it doesn't know or care which
are local and which are remote.

## Remove the mock tool

The scaffolded project shipped with a `tools/web_search.py` placeholder. The
calculus agent doesn't need it -- all its tools come from MCP. Delete it:

```bash
rm tools/web_search.py
```

If there are other example tools (like `format_citations.py` or
`code_executor.py`), remove those too. The `tools/` directory can be empty, or
you can keep it around for future local tools.

!!! note "Local tools and MCP tools coexist"
    Deleting `web_search.py` is a cleanup step, not a requirement. Local tools
    and MCP-discovered tools coexist in the same registry. If you later need a
    tool that's specific to this agent and doesn't belong in a shared MCP
    server, add it back to `tools/`.

## Update the system prompt

Open `prompts/system.md` and replace the Research Assistant prompt with one
tailored to the calculus domain:

```markdown
---
name: system
description: System prompt for the Calculus Helper agent
temperature: 0.3
---

You are a Calculus Helper. You solve calculus problems using the math tools
available to you: integration and differentiation.

## Instructions

1. When given a calculus problem, identify which tool(s) to use.
2. Call the appropriate tool with the correct expression and variable.
3. Present the result clearly, showing the original problem and the solution.
4. If a problem requires multiple steps, chain the tools logically.

## Constraints

- Always use the available tools rather than computing answers yourself.
- Show your work: state what tool you're calling and why.
- Use standard mathematical notation in your responses.
```

Three things to notice about this prompt:

**It doesn't list tool names or schemas.** BaseAgent injects tool schemas
automatically when building the system message. The prompt just describes the
*domain* and the *behavior* -- the model discovers the specifics from the
schemas.

**Temperature is 0.3.** Math problems have correct answers. A lower
temperature reduces randomness and makes the model more deterministic in its
tool selections.

**It says "use the available tools."** This nudges the model to call tools
rather than attempt mental arithmetic. Without this instruction, large language
models will sometimes try to compute integrals from memory -- and get them
wrong.

## Update the agent code

Rename the class and update the docstring to reflect the new domain. The
`step()` method stays the same -- `run_tool_calls()` already handles MCP tools
the same way it handles local ones.

```python
"""Calculus Helper — uses MCP-connected math tools to solve calculus problems."""

from __future__ import annotations

from fipsagents.baseagent import BaseAgent, StepResult


class CalculusHelper(BaseAgent):
    """An agent that solves calculus problems using MCP tools."""

    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(response.content)


if __name__ == "__main__":
    from fipsagents.baseagent import load_config
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=CalculusHelper,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )
    server.run(host=config.server.host, port=config.server.port)
```

That's the entire agent. Three lines in `step()`. `run_tool_calls()` appends
the assistant message, executes each tool call (local or MCP), appends the
results, and re-calls the model until no more tool calls remain.

!!! info "When to use a manual loop"
    `run_tool_calls()` covers the common case. If you need to intercept or
    transform tool results, apply per-tool error handling, or inject context
    between calls, the project's `CLAUDE.md` documents the manual dispatch
    pattern you'd use instead.

## Rebuild and redeploy

With the three files updated, rebuild the container and push a new deployment:

```bash
# Rebuild the image in the cluster
oc start-build calculus-agent --from-dir=. --follow -n calculus-agent

# Restart the deployment to pick up the new image
oc rollout restart deployment/calculus-agent -n calculus-agent

# Wait for the new pod to become ready
oc rollout status deployment/calculus-agent -n calculus-agent
```

Or use the Makefile shortcut:

```bash
make redeploy PROJECT=calculus-agent
```

!!! warning "MCP server must be running"
    The agent connects to the MCP server at startup. If the MCP server pod
    is not running or the service URL is wrong, the agent will log connection
    errors and start without those tools. Verify both are running before
    testing:

    ```bash
    oc get pods -n calculus-agent   # agent pod
    oc get pods -n calculus-mcp     # MCP server pod
    ```

## Test the integration

Verify the agent discovered the MCP tools:

```bash
# Note: this is the *agent* route in calculus-agent. The MCP server's route
# from Module 3 lives in calculus-mcp -- if your shell still has $ROUTE from
# that session, re-export it here so you don't curl the wrong service.
AGENT_ROUTE=$(oc get route calculus-agent -n calculus-agent -o jsonpath='{.spec.host}')

curl -sk "https://$AGENT_ROUTE/v1/agent-info" | python -m json.tool
```

You should see the MCP tools in the response:

```json
{
    "name": "calculus-agent",
    "version": "0.1.0",
    "description": "A math tutor agent that solves calculus problems step by step",
    "tools": [
        "integrate",
        "differentiate"
    ]
}
```

Now send a calculus problem and trace the flow:

```bash
curl -sk "https://$AGENT_ROUTE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Integrate x^2 dx"}]
  }' | python -m json.tool
```

Here's what happens behind the scenes:

1. **User message** arrives at the agent's `/v1/chat/completions` endpoint.
2. **`call_model()`** sends the conversation plus all tool schemas to the LLM.
3. **The LLM decides** to call the `integrate` tool with
   `{"expression": "x**2", "variable": "x"}`.
4. **`run_tool_calls()`** dispatches the call over HTTP to the MCP server.
5. **The MCP server** runs SymPy's `integrate(x**2, x)` and returns the
   result: `x**3/3`.
6. **`run_tool_calls()`** appends the result to the conversation and calls the
   model again.
7. **The LLM formats** the final answer and returns it to the user.

The response will contain the model's formatted answer, something like:

> The integral of x^2 with respect to x is **x^3/3 + C**.

!!! tip "Debugging tool calls"
    Set `LOG_LEVEL=DEBUG` in your ConfigMap to see every tool call, MCP
    request, and model interaction in the pod logs:

    ```bash
    oc logs deployment/calculus-agent -n calculus-agent --tail=50
    ```

    Look for lines like `MCP tool call: integrate` and `MCP tool result:` to
    trace the flow.

Try a few more problems to exercise different tools:

```bash
# Differentiation
curl -sk "https://$AGENT_ROUTE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Find the derivative of sin(x)*cos(x)"}]}'

# Definite integral with infinite bound
curl -sk "https://$AGENT_ROUTE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Evaluate the integral of e^(-x^2) from 0 to infinity"}]}'
```

## The architectural takeaway

Look at what you did in this module: edited three files, deleted one, ran a
rebuild. No new dependencies. No protocol code. No serialization logic.

This is the MCP value proposition. The agent is a thin orchestration layer that
routes between the user and a set of capabilities. Those capabilities can live
anywhere -- in the same pod, in a sidecar, across the cluster, or in a
different cluster entirely. The agent doesn't know and doesn't need to know. It
sees tool schemas, calls tools, and gets results.

When you want to add a new capability (say, a plotting tool), you add it to the
MCP server and redeploy. The agent picks it up at its next startup with zero
code changes.

## What's next

Your agent is calling real math tools over MCP. In
[Module 5](05-gateway-and-ui.md), you'll put a gateway and web UI in front of
it so users can interact with it through a chat interface instead of curl.
