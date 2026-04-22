# MCP Protocol

The Model Context Protocol (MCP) is a JSON-RPC 2.0 protocol that lets AI
agents discover and call tools, read resources, and retrieve prompt templates
from external servers. This page covers the protocol mechanics -- what gets
sent over the wire, how transports differ, and how to test a running server.

For a hands-on walkthrough, see [Module 3: Build an MCP Server](../03-build-mcp-server.md).

## Capabilities

MCP defines three capability types. A server can expose any combination.

| Capability | Purpose | Decorator | Example |
|-----------|---------|-----------|---------|
| **Tools** | Functions the LLM can call during reasoning | `@tool` | `integrate(expression="x**2", variable="x")` |
| **Resources** | Data the client can read on demand | `@resource` | `weather://london/current` |
| **Prompts** | Reusable prompt templates with parameters | `@prompt` | A step-by-step calculus tutor prompt |

### Tools

Tools are the most common capability. Each tool has a name, description, and
JSON Schema describing its parameters. The LLM sees this schema as part of its
tool-calling interface and decides when to invoke each tool.

```python
from typing import Annotated
from pydantic import Field
from fastmcp import Context
from fastmcp.tools import tool

@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def integrate(
    expression: Annotated[str, Field(description="The integrand in Python/SymPy syntax.")],
    variable: Annotated[str, Field(description="Variable of integration, e.g. 'x'.")],
    ctx: Context = None,
) -> dict:
    """Compute indefinite or definite integrals."""
    ...
```

**Tool annotations** are protocol-level hints about behavior. `readOnlyHint`
tells the client the tool doesn't modify state. `idempotentHint` says calling
it twice with the same input produces the same result. Clients can use these
to make retry and caching decisions.

### Resources

Resources expose read-only data via URI templates -- useful for configuration,
reference data, or anything the agent might need to look up.

```python
from fastmcp.resources import resource

@resource("weather://{city}/current", name="current_weather")
def get_weather(city: str) -> dict:
    """Current weather for a city."""
    return {"city": city, "temperature": 22}
```

### Prompts

Prompts are server-side templates with named parameters. A server can package
domain expertise as reusable instructions.

```python
from fastmcp.prompts import prompt

@prompt()
def tutor_prompt(topic: str) -> str:
    """Step-by-step calculus tutoring prompt."""
    return f"Explain {topic} step by step, showing all work."
```

Return types can be `str`, a single `PromptMessage`, or
`list[PromptMessage]` for multi-turn conversations.

## Transports

MCP supports two transport modes. The protocol messages are identical -- only
the delivery mechanism changes.

| Transport | Wire format | Typical use | How to start |
|-----------|-------------|-------------|--------------|
| **Streamable HTTP** | HTTP POST with JSON-RPC body | Production, OpenShift, remote access | `mcp.run(transport="http", host="0.0.0.0", port=8080, path="/mcp/")` |
| **STDIO** | JSON-RPC over stdin/stdout | Local development, CLI testing | `mcp.run(transport="stdio")` |

### Streamable HTTP

The production transport. The client sends HTTP POST requests to the server's
MCP endpoint (typically `/mcp/`). Each request contains a JSON-RPC 2.0
message; the response is a JSON-RPC 2.0 result.

FastMCP configures the transport from environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TRANSPORT` | `stdio` | Set to `http` for streamable HTTP |
| `MCP_HTTP_HOST` | `127.0.0.1` | Bind address |
| `MCP_HTTP_PORT` | `8000` | Listen port |
| `MCP_HTTP_PATH` | `/mcp/` | Endpoint path |

In OpenShift, the Containerfile typically sets `MCP_TRANSPORT=http` and
`MCP_HTTP_HOST=0.0.0.0` so the server listens on all interfaces at port 8080.

### STDIO

The development transport. The MCP client launches the server as a subprocess
and communicates over stdin/stdout. This is how `cmcp` (the CLI testing tool)
works:

```bash
cmcp ".venv/bin/python -m src.main" tools/list
cmcp ".venv/bin/python -m src.main" tools/call integrate '{"expression": "x**2", "variable": "x"}'
```

No network configuration needed -- the client manages the process lifecycle.

!!! note "SSE is deprecated"
    Earlier MCP drafts used Server-Sent Events (SSE) as the HTTP transport.
    Streamable HTTP replaced SSE in the 2025-03-26 protocol revision.
    FastMCP 3.x uses streamable HTTP by default.

## Protocol messages

Every MCP interaction is a JSON-RPC 2.0 request/response pair. The three
messages you'll use most often:

### initialize

The handshake. The client sends its protocol version and capabilities; the
server responds with its own.

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": { "name": "my-agent", "version": "1.0" }
  }
}
```

The server responds with its name, version, protocol version, and a
`capabilities` object listing which capability types it supports (tools,
resources, prompts).

### tools/list

Discover available tools. The response includes the name, description, and
JSON Schema for each tool's parameters.

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

### tools/call

Invoke a tool by name with arguments.

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "integrate",
    "arguments": { "expression": "x**2", "variable": "x" }
  }
}
```

The response wraps the tool's return value in the MCP content format:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"result\": \"x**3/3\", \"latex\": \"\\\\frac{x^{3}}{3}\", \"is_exact\": true, \"assumptions\": [\"integration constant omitted\"]}"
      }
    ]
  }
}
```

Equivalent methods exist for resources (`resources/list`, `resources/read`)
and prompts (`prompts/list`, `prompts/get`).

## Auto-discovery: the connect_mcp flow

When an agent starts, BaseAgent reads the `mcp_servers:` list from
`agent.yaml` and calls `connect_mcp(url)` for each entry. Here's what
happens:

1. **Create client** -- BaseAgent instantiates a `fastmcp.Client` pointed at
   the server URL.
2. **Connect** -- The client opens the connection (HTTP or STDIO) and sends
   `initialize`.
3. **List tools** -- The client calls `tools/list` and receives the full
   schema for every tool the server exposes.
4. **Register tools** -- Each discovered tool is added to the agent's tool
   registry with `llm_only` visibility. The LLM sees them in its next
   `call_model()` invocation alongside any local tools.
5. **Store client** -- The client connection is kept open for the agent's
   lifetime. Tool calls go through this persistent connection.

```yaml
# agent.yaml
mcp_servers:
  - url: ${MCP_CALCULUS_URL:-http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/}
```

On the server side, auto-discovery of *components* works through
`FileSystemProvider`. The server bootstrap creates one provider per capability
directory:

```python
from fastmcp.server.providers import FileSystemProvider

providers = [
    FileSystemProvider(SRC_ROOT / "tools", reload=hot_reload),
    FileSystemProvider(SRC_ROOT / "resources", reload=hot_reload),
    FileSystemProvider(SRC_ROOT / "prompts", reload=hot_reload),
]
mcp = FastMCP(name, providers=providers, middleware=middleware)
```

Drop a Python file with a `@tool`-decorated function into `src/tools/`, and
the server picks it up automatically. No registration code, no import lists.
With `reload=True` (controlled by the `MCP_HOT_RELOAD` env var), the server
detects new files at runtime.

!!! tip "Standalone decorators"
    FastMCP 3.x uses standalone decorators (`from fastmcp.tools import tool`)
    rather than a shared server instance. Each component file is
    self-contained -- it never imports an `mcp` object. This is what makes
    directory-scanning discovery possible.

## Testing with curl

Any streamable-HTTP server can be tested with plain curl. Set `URL` to a
local address or an OpenShift route:

```bash
# Local
URL="http://localhost:8000/mcp/"

# Or from an OpenShift route
URL="https://$(oc get route mcp-server -n calculus-mcp -o jsonpath='{.spec.host}')/mcp/"
```

The streamable-http transport requires two headers on every request:
`Content-Type: application/json` and `Accept: application/json,
text/event-stream`. After `initialize`, subsequent requests must also include
the `Mcp-Session-Id` returned in the response headers. Add `-sk` for
self-signed TLS certs.

```bash
# 1. Initialize -- dump headers so we can capture the session ID
curl -s "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -D /tmp/mcp-headers.txt \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

# Capture session ID from response headers
SESSION=$(grep -i mcp-session-id /tmp/mcp-headers.txt | tr -d '\r' | awk '{print $2}')

# 2. List tools
curl -s "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# 3. Call a tool
curl -s "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"integrate","arguments":{"expression":"x**2","variable":"x"}}}'
```

Responses arrive as SSE events, prefixed with `event: message\ndata: ...`.
The JSON payload follows on the `data:` line.

For deployed servers, `mcp-test-mcp` wraps the handshake into one-line
commands:

```bash
mcp-test-mcp list_tools --server-url "$URL"
mcp-test-mcp test_tool --server-url "$URL" \
  --tool-name integrate \
  --params '{"expression": "x**2", "variable": "x"}'
```


## Authentication

MCP servers can require authentication using JWT tokens. FastMCP provides
`JWTVerifier` for token validation and `RemoteAuthProvider` for OAuth 2.0
Protected Resource metadata (RFC 9728).

Auth is configured via environment variables on the server:

| Variable | Purpose |
|----------|---------|
| `MCP_AUTH_JWT_ALG` | JWT algorithm (RS256, HS256, etc.). Auth disabled if unset. |
| `MCP_AUTH_JWT_SECRET` | Shared secret for HMAC algorithms |
| `MCP_AUTH_JWT_PUBLIC_KEY` | Public key for RSA/EC algorithms |
| `MCP_AUTH_JWT_JWKS_URI` | JWKS endpoint URL (alternative to static key) |
| `MCP_AUTH_JWT_ISSUER` | Expected token issuer |
| `MCP_AUTH_JWT_AUDIENCE` | Expected token audience |
| `MCP_AUTH_REQUIRED_SCOPES` | Comma-separated default required scopes |

Individual tools can require additional scopes using the `auth` parameter:

```python
from fastmcp.server.auth import require_scopes
from fastmcp.tools import tool

@tool(auth=require_scopes("admin"))
async def admin_only_tool() -> str:
    """Only accessible with admin scope."""
    return "secret data"
```

When auth is enabled, clients must include a `Bearer` token in the
`Authorization` header of their HTTP requests.

## Error handling

MCP uses JSON-RPC 2.0 error responses. FastMCP's `ToolError` exception maps
to the standard error format:

```python
from fastmcp.exceptions import ToolError

@tool()
async def my_tool(expression: str) -> str:
    if not expression.strip():
        raise ToolError("Expression cannot be empty.")
    ...
```

The client receives a JSON-RPC error response with the message. When
building tools for agent consumption, write error messages that help the LLM
recover -- state what went wrong and what valid input looks like.

## Quick reference

Common protocol methods:

| Method | Direction | Purpose |
|--------|-----------|---------|
| `initialize` | Client -> Server | Handshake, exchange capabilities |
| `tools/list` | Client -> Server | Discover available tools |
| `tools/call` | Client -> Server | Invoke a tool |
| `resources/list` | Client -> Server | Discover available resources |
| `resources/read` | Client -> Server | Read a resource by URI |
| `prompts/list` | Client -> Server | Discover available prompts |
| `prompts/get` | Client -> Server | Retrieve a prompt template |
| `notifications/initialized` | Client -> Server | Client ready (after initialize) |
