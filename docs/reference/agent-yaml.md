# agent.yaml Reference

Complete reference for the `agent.yaml` configuration file used by BaseAgent.
Every value supports `${VAR:-default}` environment variable substitution so the
same file works unchanged for local development and OpenShift deployment.

Local development uses the baked-in defaults. Production overrides only what
differs, typically via ConfigMap or Secrets.

## Environment variables

All env vars that `agent.yaml` reads, in one place. Set these via ConfigMap or
Secrets to override defaults without editing the file.

| Variable | Field | Default | Notes |
|----------|-------|---------|-------|
| `AGENT_NAME` | `agent.name` | `my-agent` | |
| `MODEL_ENDPOINT` | `model.endpoint` | `http://llamastack:8321/v1` | OpenAI-compatible `/v1` URL |
| `MODEL_NAME` | `model.name` | `meta-llama/Llama-3.3-70B-Instruct` | Model identifier for the endpoint |
| `MODEL_PROVIDER` | `model.provider` | `openai` | LLM backend; non-openai values route through adapter sidecar |
| `OPENAI_API_KEY` | *(SDK)* | -- | Required by the OpenAI SDK even for unauthenticated endpoints; set to any non-empty string |
| `MAX_ITERATIONS` | `loop.max_iterations` | `100` | |
| `LOG_LEVEL` | `logging.level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `HOST` | `server.host` | `0.0.0.0` | |
| `PORT` | `server.port` | `8080` | |
| `STORAGE_BACKEND` | `server.storage.backend` | *(null)* | `null`, `sqlite`, `postgres` |
| `SQLITE_PATH` | `server.storage.sqlite_path` | `./agent.db` | Path to SQLite file |
| `DATABASE_URL` | `server.storage.database_url` | -- | PostgreSQL connection string |
| `SESSIONS_ENABLED` | `server.sessions.enabled` | `false` | Enable session persistence |
| `TRACES_ENABLED` | `server.traces.enabled` | `false` | Enable trace collection |
| `METRICS_ENABLED` | `server.metrics.enabled` | `false` | Enable Prometheus metrics at `GET /metrics` |
| `FEEDBACK_ENABLED` | `server.feedback.enabled` | `false` | Enable user feedback collection at `POST/GET /v1/feedback` |
| `OTEL_ENDPOINT` | `server.traces.otel_endpoint` | -- | OTLP gRPC endpoint for trace export |
| `OTEL_SERVICE_NAME` | `server.traces.service_name` | `fipsagents` | Service name for OTEL spans |
| `MEMORY_BACKEND` | `memory.backend` | *(auto-detect)* | `memoryhub`, `sqlite`, `pgvector`, `custom`, `null` |
| `SECURITY_MODE` | `security.mode` | `enforce` | `enforce` or `observe` |
| `TOOL_INSPECTION_ENABLED` | `security.tool_inspection.enabled` | `true` | |
| `SANDBOX_URL` | *(tool)* | `http://localhost:8000` | Set automatically by Helm when `sandbox.enabled=true` |

## agent

Agent identity metadata used for logging and the `/v1/agent-info` endpoint.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `my-agent` | Agent name. Populated by `/create-agent` from AGENT_PLAN.md. |
| `description` | string | *(empty)* | Brief description of what the agent does. |
| `version` | string | `0.1.0` | Semantic version for the agent. |

```yaml
agent:
  name: ${AGENT_NAME:-my-agent}
  description: "A brief description of what this agent does"
  version: 0.1.0
```

## model

LLM provider and generation settings. The `endpoint` must be an
OpenAI-compatible `/v1` URL -- vLLM, LlamaStack, llm-d, or any compatible API.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `endpoint` | string | `http://llamastack:8321/v1` | OpenAI-compatible API base URL. |
| `name` | string | `meta-llama/Llama-3.3-70B-Instruct` | Model identifier passed to the endpoint. |
| `provider` | string | `openai` | LLM backend. Valid values: `openai` (any OpenAI-compatible endpoint -- default), `anthropic`, `bedrock`, `bedrock-converse`, `azure`, `openai-compatible`, `ollama`, `llama-cpp`, `vertex`. When provider is non-openai, the agent runtime auto-rewrites the endpoint to the LLM adapter sidecar at `localhost:8081/v1`. |
| `temperature` | float | `0.7` | Sampling temperature. |
| `max_tokens` | int | `4096` | Maximum tokens per completion. |

```yaml
model:
  endpoint: ${MODEL_ENDPOINT:-http://llamastack:8321/v1}
  name: ${MODEL_NAME:-meta-llama/Llama-3.3-70B-Instruct}
  provider: ${MODEL_PROVIDER:-openai}
  temperature: 0.7
  max_tokens: 4096
```

## mcp_servers

Remote MCP servers the agent connects to at startup. BaseAgent discovers three
capability types from each server:

- **Tools** -- auto-registered with `llm_only` visibility. The LLM decides when to call them.
- **Prompts** -- available via `self.get_mcp_prompt(name, arguments)`. Discover with `self.list_mcp_prompts()`.
- **Resources** -- available via `self.read_resource(uri)`. Discover with `self.list_mcp_resources()` and `self.list_mcp_resource_templates()`.

Each entry needs either a `url` (HTTP transport) or a `command` (stdio transport):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | one of `url` or `command` | HTTP endpoint for the MCP server. |
| `command` | string | one of `url` or `command` | Path to an MCP server binary (stdio transport). |
| `args` | list[string] | no | Command-line arguments for stdio servers. |
| `env` | dict | no | Environment variables passed to stdio servers. Supports `${VAR}` substitution. |

```yaml
# HTTP transport
mcp_servers:
  - url: ${MCP_SEARCH_URL:-http://search-mcp:8080/mcp}

# stdio transport
mcp_servers:
  - command: /path/to/mcp-server
    args: [--verbose]
    env: {API_KEY: "${SEARCH_API_KEY}"}
```

## tools

Local tools auto-discovered from a directory at startup.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `local_dir` | string | `./tools` | Directory containing tool files. Files starting with `_` are skipped. |
| `visibility_default` | string | `agent_only` | Default visibility for tools that don't declare their own via `@tool`. One of: `agent_only`, `llm_only`, `both`. |

Visibility determines who can call the tool:

| Value | Caller | Use for |
|-------|--------|---------|
| `agent_only` | Agent code via `self.use_tool()` | Validation, formatting, internal logic. |
| `llm_only` | LLM via tool calling | Search, retrieval, information gathering. |
| `both` | Either | Rare -- only when genuinely needed by both. |

MCP-discovered tools always default to `llm_only` regardless of `visibility_default`.

```yaml
tools:
  local_dir: ./tools
  visibility_default: agent_only
```

## prompts

Prompt templates loaded from Markdown files with YAML frontmatter.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dir` | string | `./prompts` | Directory containing prompt files. |
| `system` | string | `system` | Prompt file to load as the system prompt (resolves to `prompts/system.md`). |

The system prompt is assembled by `build_system_prompt()`, which loads the
designated prompt file, appends all rules from `rules/`, and appends the skill
manifest.

```yaml
prompts:
  dir: ./prompts
  system: system
```

## loop

Agent loop controls that govern execution of `step()` calls within a single
`run()` invocation.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_iterations` | int | `100` | Hard ceiling on `step()` calls per `run()`. Prevents runaway loops. |
| `backoff.initial` | float | `1.0` | First retry delay in seconds. |
| `backoff.max` | float | `30.0` | Ceiling on retry delay in seconds. |
| `backoff.multiplier` | float | `2.0` | Factor applied after each retry. Must be > 1.0. |

Backoff is applied when `step()` raises a retryable error.

```yaml
loop:
  max_iterations: ${MAX_ITERATIONS:-100}
  backoff:
    initial: 1.0
    max: 30.0
    multiplier: 2.0
```

## logging

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `level` | string | `INFO` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |

Use `DEBUG` locally for verbose output. Keep `INFO` or `WARNING` in production.

```yaml
logging:
  level: ${LOG_LEVEL:-INFO}
```

## server

HTTP server binding for the OpenAI-compatible API. The Helm chart's
`service.port` should match `port`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `0.0.0.0` | Bind address. Use `127.0.0.1` for local-only testing. |
| `port` | int | `8080` | Bind port. |

```yaml
server:
  host: ${HOST:-0.0.0.0}
  port: ${PORT:-8080}
```

### server.storage

Shared storage backend for sessions and traces. When `backend` is `null`
(the default), both features degrade to no-ops -- fully backward-compatible.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | string | `null` | `null`, `sqlite`, or `postgres`. When null, sessions and traces are no-ops. |
| `sqlite_path` | string | `./agent.db` | Path to the SQLite file. Only used when `backend: sqlite`. |
| `database_url` | string | -- | PostgreSQL connection string. Only used when `backend: postgres`. |

```yaml
server:
  storage:
    backend: ${STORAGE_BACKEND:-}
    sqlite_path: ${SQLITE_PATH:-./agent.db}
    # database_url: ${DATABASE_URL}
```

### server.sessions

Session persistence. Requires a storage backend to be configured.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable session persistence. |
| `max_age_hours` | int | `168` | Sessions expire after this many hours. |

```yaml
server:
  sessions:
    enabled: ${SESSIONS_ENABLED:-false}
    max_age_hours: 168
```

### server.traces

Trace collection and export. Requires a storage backend (or OTEL exporter).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable trace collection. |
| `max_age_hours` | int | `168` | Traces expire after this many hours. |
| `sampling_rate` | float | `1.0` | Fraction of requests to trace (0.0--1.0). |
| `exporter` | string | *(none)* | `store` (persist to storage backend), `otel` (export via OTLP), or `null`. `otel` requires the `[otel]` extra. |
| `otel_endpoint` | string | -- | OTLP gRPC endpoint (e.g. `http://otel-collector:4317`). Required when `exporter: otel`. |
| `service_name` | string | `fipsagents` | Service name for OTEL spans. |

```yaml
server:
  traces:
    enabled: ${TRACES_ENABLED:-false}
    max_age_hours: 168
    sampling_rate: 1.0
    # exporter: otel
    # otel_endpoint: ${OTEL_ENDPOINT:-http://otel-collector:4317}
    # service_name: ${OTEL_SERVICE_NAME:-fipsagents}
```

### server.metrics

Prometheus metrics exposed at `GET /metrics`. Requires the `[metrics]` extra
(`prometheus_client`).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Prometheus metrics at `GET /metrics`. |

```yaml
server:
  metrics:
    enabled: ${METRICS_ENABLED:-false}
```

### server.feedback

User feedback collection at `POST /v1/feedback`, `GET /v1/feedback`, and
`GET /v1/feedback/stats`. Requires a storage backend for persistence;
without one, POSTs are accepted and discarded.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable feedback collection endpoints. |
| `max_age_hours` | int | `720` | Records expire after this many hours (default: 30 days). |

```yaml
server:
  feedback:
    enabled: ${FEEDBACK_ENABLED:-false}
    max_age_hours: 720
```

Records carry `rating` (`1` or `-1`), `trace_id` (for joining to trace
data), optional `comment` and `correction`, plus `model_id`, `latency_ms`,
`turn_index`, and `agent_type` for slicing in the stats endpoint.

## memory

Memory backend configuration. When `backend` is omitted, auto-detects by
looking for `.memoryhub.yaml`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | string | *(auto-detect)* | Backend to use. See values below. |
| `config_path` | string | `.memoryhub.yaml` | Path to the backend-specific config file. |
| `backend_class` | string | `null` | Dotted import path. Only used when `backend: custom`. |

| Backend | Config file | Description |
|---------|-------------|-------------|
| `memoryhub` | `.memoryhub.yaml` | MemoryHub SDK. Default when `.memoryhub.yaml` exists. |
| `sqlite` | `.memory-sqlite.yaml` | Local SQLite with FTS5 search. Zero dependencies. |
| `pgvector` | `.memory-pgvector.yaml` | PostgreSQL + pgvector for semantic search. |
| `custom` | -- | Bring your own `MemoryClientBase` subclass via `backend_class`. |
| `null` | -- | Explicitly disable memory. |

```yaml
memory:
  backend: ${MEMORY_BACKEND:-}
  config_path: .memoryhub.yaml
  # backend_class: myproject.memory.RedisMemoryClient
```

## security

Security inspection, audit logging, and enforcement. The global `mode` sets the
default; per-layer `mode` fields override it.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `enforce` | `enforce` blocks on findings. `observe` logs but allows execution. |
| `tool_inspection.enabled` | bool | `true` | Enable tool call inspection. |
| `tool_inspection.mode` | string | *(inherits global)* | Override global mode for tool inspection. |
| `guardrails.mode` | string | *(inherits global)* | Override global mode for guardrails. |

```yaml
security:
  mode: ${SECURITY_MODE:-enforce}
  tool_inspection:
    enabled: ${TOOL_INSPECTION_ENABLED:-true}
    # mode: observe        # override global mode for this layer
  # guardrails:
  #   mode: observe        # override global mode for guardrails
```

## nodes

Node deployment topology. Maps workflow node names to local or remote execution.
Nodes default to local (in-process). The runner auto-wraps remote nodes so the
graph definition stays topology-agnostic.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `<node>.type` | string | `local` | `local` for in-process, `remote` for HTTP delegation. |
| `<node>.endpoint` | string | -- | Base URL of the remote agent. Required when `type: remote`. |
| `<node>.path` | string | `/process` | HTTP path appended to the endpoint. |
| `<node>.timeout` | float | `30.0` | Request timeout in seconds. |
| `<node>.retries` | int | `2` | HTTP-level retries. The runner also retries via `node_retries`. |

Remote contract: `POST {endpoint}{path}` with body
`{"state": {...}, "state_type": "fully.qualified.ClassName"}`, response
`{"state": {...}}`.

```yaml
nodes:
  classify:
    type: local
  research:
    type: remote
    endpoint: ${RESEARCH_AGENT_URL:-http://research-agent:8080}
    path: /process
    timeout: 30.0
    retries: 2
```

Set `nodes: {}` when no remote nodes are needed.

## sandbox

Code execution sandbox. The `code_executor` tool sends LLM-generated Python to
a sidecar container for safe execution. The sidecar runs in the same pod at
`localhost:8000`.

Enable in Helm values:

```yaml
sandbox:
  enabled: true
  image:
    repository: code-sandbox
    tag: latest
```

For local development, start the sidecar manually:

```bash
cd sandbox && uvicorn sandbox.app:app --port 8000
```

Available modules: `math`, `statistics`, `itertools`, `functools`, `re`,
`datetime`, `collections`, `json`, `csv`, `string`, `textwrap`, `decimal`,
`fractions`, `random`, `operator`, `typing`.

## Annotated full example

A fully configured `agent.yaml` with production-ready env var substitution:

```yaml
agent:
  name: ${AGENT_NAME:-calculus-agent}
  description: "An agent that solves calculus problems step by step"
  version: 1.0.0

model:
  endpoint: ${MODEL_ENDPOINT:-http://llamastack:8321/v1}
  name: ${MODEL_NAME:-meta-llama/Llama-3.3-70B-Instruct}
  provider: ${MODEL_PROVIDER:-openai}
  temperature: 0.7
  max_tokens: 4096

mcp_servers:
  - url: ${MCP_CALCULUS_URL:-http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/}

tools:
  local_dir: ./tools
  visibility_default: agent_only

prompts:
  dir: ./prompts
  system: system

loop:
  max_iterations: ${MAX_ITERATIONS:-100}
  backoff:
    initial: 1.0
    max: 30.0
    multiplier: 2.0

logging:
  level: ${LOG_LEVEL:-INFO}

server:
  host: ${HOST:-0.0.0.0}
  port: ${PORT:-8080}
  storage:
    backend: ${STORAGE_BACKEND:-}
    sqlite_path: ${SQLITE_PATH:-./agent.db}
    # database_url: ${DATABASE_URL}
  sessions:
    enabled: ${SESSIONS_ENABLED:-false}
    max_age_hours: 168
  traces:
    enabled: ${TRACES_ENABLED:-false}
    sampling_rate: 1.0
    # exporter: otel
    # otel_endpoint: ${OTEL_ENDPOINT:-http://otel-collector:4317}
    # service_name: ${OTEL_SERVICE_NAME:-fipsagents}
  metrics:
    enabled: ${METRICS_ENABLED:-false}

memory:
  backend: ${MEMORY_BACKEND:-}
  config_path: .memoryhub.yaml

security:
  mode: ${SECURITY_MODE:-enforce}
  tool_inspection:
    enabled: ${TOOL_INSPECTION_ENABLED:-true}

nodes: {}
```
