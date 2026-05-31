# Agent Memory with MemoryHub

Throughout Modules 1--11, the calculus-agent ran with memory disabled
(`NullMemoryClient`). That was fine -- every request was self-contained, and
the agent didn't need to remember anything across sessions. A calculus tutor
that forgets everything between conversations is still useful, but it isn't
great -- it can't remember that a student prefers step-by-step solutions, that
they're working through a textbook chapter on Taylor series, or that they
asked the same integral yesterday.

Cross-session memory matters when agents need to retain user preferences, prior
results, or organizational knowledge. MemoryHub provides governed, scoped
memory with semantic search: the agent writes facts into a shared store, and
later retrieves them by meaning rather than exact match. The backend is a
PostgreSQL + pgvector database fronted by an MCP server, so the agent talks to
memory the same way it talks to any other tool.

This module covers two integration paths. Part 1 uses fips-agents -- what
you've been building with since Module 1. Part 2 shows the same MemoryHub
backend accessed through kagenti ADK's A2A extension system, which is useful
context if your organization uses Kagenti (see
[Where to Go Next](../where-next.md#kagenti) for background).

!!! info "Prerequisites"
    - Modules 0--2 complete (working cluster, deployed calculus-agent)
    - A MemoryHub instance -- either deployed to your cluster (this module
      walks through that) or accessible at a known URL

## Part 1: fips-agents

This section adds MemoryHub to the calculus-agent you built in Modules 1--4.
By the end, the agent will persist memories across sessions and retrieve them
via semantic search.

### Deploy MemoryHub

MemoryHub is an independent project that deploys its own namespace, database,
and MCP endpoint. Clone the repository and install it:

```bash
git clone https://github.com/redhat-ai-americas/memory-hub.git
cd memory-hub
make install
```

The `make install` target creates the `memory-hub-mcp` namespace and deploys
four components: PostgreSQL with pgvector, the MemoryHub MCP server, an OAuth
service for credential management, and a Route for external access.

Verify the MCP endpoint is reachable:

```bash
curl -sf https://memory-hub-mcp-memory-hub-mcp.apps.<cluster>/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python -m json.tool
```

Replace `<cluster>` with your cluster's apps domain. A successful response
lists MemoryHub's MCP tools: `register_session` and `memory` (a unified tool
whose `action` parameter selects the operation -- `search`, `write`, `list`,
etc.).

!!! tip "Local development without a cluster deployment"
    If you already have a MemoryHub instance running elsewhere, you can skip
    the deploy step entirely. Set `MEMORYHUB_URL` and `MEMORYHUB_API_KEY` as
    environment variables pointing at the existing instance and proceed to the
    wiring step.

### Wire memory into calculus-agent

In your `calculus-agent/` project, run the `/add-memory` slash command in
Claude Code. The slash command walks through the configuration changes
interactively:

1. Creates or updates `.memoryhub.yaml` with `server_url` pointing at your
   MemoryHub MCP endpoint
2. Updates `agent.yaml` to set `memory.backend: memoryhub` and
   `memory.config_path: .memoryhub.yaml`
3. Updates the `Containerfile` to copy `.memoryhub.yaml` into the image
4. Optionally adds MemoryHub as an MCP server so the LLM can call memory
   tools directly

The key configuration result is two files. In `agent.yaml`, add the `memory:`
block:

```yaml
# agent.yaml
memory:
  backend: memoryhub
  config_path: .memoryhub.yaml
```

And the MemoryHub connection config:

```yaml
# .memoryhub.yaml (key fields)
server_url: https://memory-hub-mcp-memory-hub-mcp.apps.<cluster>/mcp/
memory_loading:
  mode: focused
  pattern: lazy
```

The `mode: focused` setting tells the agent to load only memories relevant to
the current conversation (via semantic search), rather than dumping the entire
memory store into context. The `pattern: lazy` setting defers memory loading
until the agent actually needs it, keeping cold-start times low.

### Use memory in agent code

BaseAgent exposes the memory backend through `self.memory`. Two operations
cover the common case -- searching for relevant memories and writing new ones:

```python
# In your agent's step() method
results = await self.memory.search("calculus preferences", max_results=5)

await self.memory.write(
    content="User prefers step-by-step solutions",
    content_type="behavioral",
    scope="user",
    weight=0.8,
)
```

The `scope` parameter controls visibility. MemoryHub uses a five-tier scoping
model:

| Scope | Visible to | Example |
|-------|-----------|---------|
| `user` | One user across all agents | "Prefers LaTeX notation" |
| `project` | All users in a project | "Project uses SI units" |
| `role` | All agents with a given role | "Calculus tutors show worked steps" |
| `organizational` | All agents in an org | "Company style guide rules" |
| `enterprise` | All agents everywhere | "Compliance: no PII in responses" |

The `content_type` parameter classifies what the memory represents:
`experiential` (events and interactions), `knowledge` (facts and information),
or `behavioral` (preferences and patterns). MemoryHub uses this for curation
and retrieval ranking.

The `weight` parameter (0.0--1.0) signals how important the memory is.
Higher-weight memories rank higher in search results and are less likely to be
pruned during curation.

### Test it

Start the agent locally with memory enabled:

```bash
cd calculus-agent
make run
```

Send a message that establishes a preference:

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "I prefer step-by-step solutions with LaTeX formatting."}]
  }' | python -m json.tool
```

Stop the agent (`Ctrl+C`), then restart it and ask a question that should
trigger memory retrieval:

```bash
make run
# In another terminal:
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is the integral of x^2?"}]
  }' | python -m json.tool
```

If memory is working, the response should reflect the stored preference --
step-by-step format with LaTeX. Verify directly against MemoryHub to confirm
the memory was persisted:

```bash
curl -s https://memory-hub-mcp-memory-hub-mcp.apps.<cluster>/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {"name": "memory", "arguments": {"action": "search", "query": "preferences", "max_results": 5}},
    "id": 1
  }' | python -m json.tool
```

### Curation and duplicate detection

MemoryHub doesn't accept every write blindly. A curation layer checks each
incoming memory against existing content and configured rules before
persisting it. If the write is too similar to an existing memory, MemoryHub
flags it with a similarity warning and a recommendation.

Try it: write the same fact twice. The first write succeeds. The second
gets flagged as a possible duplicate:

```python
# First write -- succeeds
await self.memory.write(
    content="User prefers step-by-step solutions",
    content_type="behavioral",
    scope="user",
    weight=0.8,
)

# Second write -- flagged as possible duplicate
result = await self.memory.write(
    content="The user prefers step-by-step solutions",
    content_type="behavioral",
    scope="user",
    weight=0.8,
)
```

The response includes a similarity flag, the near-duplicate's ID and score,
and a recommendation:

```json
{
  "blocked": false,
  "reason": "possible_duplicate",
  "detail": "Memory is 99% similar to existing memory b7ba6e8e-...",
  "nearest_score": 0.9869,
  "existing_memory_id": "b7ba6e8e-...",
  "recommendation": "update_existing"
}
```

Note that `"blocked"` is `false` -- by default, MemoryHub flags near-duplicates
rather than rejecting them outright. The write still succeeds, but the
`recommendation` field tells the agent it should update the existing memory
instead of creating duplicates. Whether near-duplicates are hard-blocked
depends on the MemoryHub instance's similarity threshold configuration.

The fips-agents `MemoryClient` surfaces this as a structured return value; in
kagenti ADK (Part 2), the equivalent is a `MemoryRejectionError` exception.

This is the curation system working as designed. Without it, agents that
write aggressively (common with LLM-driven memory) would fill the store with
redundant entries, degrading search quality over time.

### Deploy with memory enabled

Redeploy the agent to OpenShift:

```bash
make deploy
```

The agent pod needs credentials to reach MemoryHub. There are two paths
depending on your MemoryHub configuration:

**API key (simple path):** Create an OpenShift Secret with the key and
reference it in your Helm values:

```bash
oc create secret generic memoryhub-creds \
  --from-literal=MEMORYHUB_API_KEY=<your-key> \
  -n calculus-agent
```

**OAuth (production path):** Create a Secret with the OAuth client credentials:

```bash
oc create secret generic memoryhub-creds \
  --from-literal=MEMORYHUB_AUTH_URL=https://auth.example.com/token \
  --from-literal=MEMORYHUB_CLIENT_ID=<client-id> \
  --from-literal=MEMORYHUB_CLIENT_SECRET=<client-secret> \
  -n calculus-agent
```

In both cases, update your Helm values to mount the Secret as environment
variables in the agent pod.

!!! warning "Silent fallback to NullMemoryClient"
    If the API key or OAuth credentials are missing or invalid, the agent does
    not crash -- it silently falls back to `NullMemoryClient` and runs without
    memory. This is safe but easy to miss. Check the pod logs for the string
    `memory disabled` or `NullMemoryClient` after deployment to confirm memory
    is actually active.

## Part 2: The kagenti ADK approach

This section shows the same MemoryHub backend accessed through kagenti ADK's
A2A extension system. You don't need to deploy anything new -- the MemoryHub
instance from Part 1 is the same backend. The difference is in how credentials
flow: fips-agents stores credentials agent-side (env vars or Secrets), while
kagenti ADK pushes them client-side through a fulfillment pattern.

This is useful context if your organization uses Kagenti. See
[Where to Go Next](../where-next.md#kagenti) for installation guidance and
caveats -- this section covers only the MemoryHub integration, not the
broader platform.

### Install the dependency

```bash
uv add 'kagenti-adk[memoryhub]>=0.5.3'
```

### Server-side wiring

Kagenti ADK uses an `Annotated` injection pattern to declare that an agent
*demands* MemoryHub. The runtime resolves the demand at call time, injecting
a connected store instance:

```python
from typing import Annotated
from kagenti_adk.a2a.extensions import MemoryHubExtensionSpec
from kagenti_adk.server.store.memoryhub_memory_store import MemoryHubExtensionServer

@server.agent()
async def my_agent(
    input: Message,
    context: RunContext,
    memoryhub: Annotated[
        MemoryHubExtensionServer,
        MemoryHubExtensionSpec.single_demand(),
    ],
):
    store = memoryhub.store(context.context_id)
    results = await store.search("query", max_results=5)
    await store.create(
        "content",
        scope="project",
        project_id="my-project",
        weight=0.7,
    )
```

The `single_demand()` declaration tells the A2A framework that this agent
requires exactly one MemoryHub instance. The framework advertises this
requirement in the agent's A2A card, so clients know what to supply.

### Client-side fulfillment

The client reads the agent's A2A card, discovers the MemoryHub demand, and
supplies the URL and credentials in request metadata. This keeps secrets on the
client side -- the server never stores them:

```python
from kagenti_adk.a2a.extensions import (
    MemoryHubExtensionClient,
    MemoryHubExtensionSpec,
    MemoryHubFulfillment,
)
from pydantic import SecretStr

spec = MemoryHubExtensionSpec.from_agent_card(agent_card)
metadata = MemoryHubExtensionClient(spec).fulfillment_metadata(
    memoryhub_fulfillments={
        "default": MemoryHubFulfillment(
            url="https://memoryhub.example.com/mcp/",
            api_key=SecretStr("..."),
        )
    }
)
```

The fulfillment metadata travels with the request. The server extracts it,
connects to MemoryHub with the supplied credentials, and disposes of the
connection when the request completes.

### Environment variable fallback

For development and testing, kagenti ADK can resolve MemoryHub credentials
from environment variables instead of client-side fulfillment:

| Variable | Purpose |
|----------|---------|
| `MEMORYHUB_URL` | MemoryHub MCP endpoint URL |
| `MEMORYHUB_API_KEY` | Static API key (simple path) |
| `MEMORYHUB_AUTH_URL` | OAuth token endpoint (OAuth path) |
| `MEMORYHUB_CLIENT_ID` | OAuth client ID |
| `MEMORYHUB_CLIENT_SECRET` | OAuth client secret |

When these variables are set, the server satisfies its own demand without
requiring client-side fulfillment. This is convenient for local development
but bypasses the security benefit of client-side credential management.

## Comparison

Both approaches use the same MemoryHub backend and the same five-tier scoping
model. The differences are in wiring and credential flow:

| Concern | fips-agents | kagenti ADK |
|---------|-------------|-------------|
| Configuration | `agent.yaml` + `.memoryhub.yaml` | A2A extension declaration |
| Dependency | `memoryhub` (pip) | `kagenti-adk[memoryhub]` (pip) |
| Memory access | `self.memory.search()` / `.write()` | `store.search()` / `.create()` |
| Credential management | Agent-side (env vars or Secret) | Client-side (fulfillment metadata) |
| Backend | MemoryHub MCP | MemoryHub MCP |
| Scoping model | Same 5-tier scoping | Same 5-tier scoping |
| Curation flagging | Handled by `MemoryClient` | `MemoryRejectionError` exception |

The fips-agents path is simpler to set up and fits naturally into the
`agent.yaml` configuration model you've been using throughout the tutorial. The
kagenti ADK path is more flexible in multi-tenant environments where you don't
want agents storing credentials -- the client supplies them per-request.

## What's next

The memory integration works with any agent that connects to MemoryHub -- the
backend is the same regardless of framework. If you're exploring multi-agent
architectures, the [Where to Go Next](../where-next.md#kagenti) page covers
Kagenti's broader platform capabilities including A2A communication, workload
identity, and MCP gateway routing. For fips-agents, the `agent.yaml` reference
documents [additional memory backends](../reference/agent-yaml.md#memory)
including SQLite and pgvector for environments where MemoryHub isn't available.
