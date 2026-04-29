# 8. Production Hardening

Your full stack is deployed: agent, MCP server, gateway, UI, and code execution
sandbox. Everything works in development. This final module covers what it takes
to run the stack in production -- secrets management, FIPS compliance,
authentication, security policy, resource limits, monitoring, and
observability.

## FIPS compliance

**Federal Information Processing Standards** (FIPS 140-2/140-3) mandate the use
of validated cryptographic modules. FIPS compliance is required for U.S.
government workloads and many enterprise environments. If your OpenShift cluster
runs with FIPS mode enabled, every container in the cluster must use
FIPS-validated crypto.

Red Hat UBI base images are FIPS-capable out of the box. When the host kernel
has `fips=1` set, UBI's OpenSSL automatically restricts itself to
FIPS-validated algorithms. No application-level configuration is needed.

To verify FIPS mode is active in a running pod:

```bash
oc exec deployment/calculus-agent -n calculus-agent -- \
  cat /proc/sys/crypto/fips_enabled
```

A return value of `1` means FIPS mode is active. A return value of `0` means
the host kernel does not have FIPS enabled.

!!! tip "What breaks under FIPS"
    MD5 hashing raises an error unless called with `usedforsecurity=False`.
    TLS is restricted to AEAD cipher suites (AES-GCM, AES-CCM). If your agent
    calls an external endpoint that requires legacy ciphers (CBC, RC4), the TLS
    handshake will fail. The fix is on the remote endpoint, not your agent.

## The litellm migration

The framework originally used **litellm** as an LLM abstraction layer. Two
problems forced a switch:

1. **FIPS incompatibility.** litellm's dependency tree pulls in cryptographic
   libraries that are not FIPS-validated. On a FIPS-enabled cluster, these
   libraries either fail at import time or silently use non-compliant algorithms.

2. **Supply chain compromise.** litellm versions `1.82.7` and `1.82.8` were
   compromised in a supply chain attack (March 2026). The malicious versions
   exfiltrated API keys to an external endpoint.

The fix was straightforward: replace litellm with the `openai` async SDK.
vLLM, LlamaStack, llm-d, and most inference servers expose an
OpenAI-compatible API, so litellm's abstraction layer was adding complexity
without adding value. The result is a simpler dependency tree that is easier to
audit, FIPS-compliant, and free of supply chain risk.

!!! warning "Never install litellm 1.82.7 or 1.82.8"
    These versions are compromised. If you encounter them in a lockfile or
    dependency tree, pin to `>=1.83.0` or `<=1.82.6`.

The takeaway: fewer dependencies means a smaller attack surface. Prefer
standard SDKs over abstraction layers when the abstraction doesn't carry its
weight.

## Secrets management

Production credentials must never appear in `agent.yaml`, prompts, or source
code. OpenShift Secrets are the standard mechanism for injecting sensitive
values at runtime.

### Create a Secret

The `openai` SDK requires `OPENAI_API_KEY` to be set, even when calling
unauthenticated endpoints like vLLM (set it to any non-empty string in that
case). For endpoints that require real credentials, create a Secret:

```bash
oc create secret generic llm-credentials \
  --from-literal=OPENAI_API_KEY=sk-your-real-key-here \
  -n calculus-agent
```

### Mount via Helm values

The Helm chart's `env` section supports `secretKeyRef` for injecting Secret
values as environment variables. Add this to your `values.yaml`:

```yaml
env:
  - name: OPENAI_API_KEY
    valueFrom:
      secretKeyRef:
        name: llm-credentials
        key: OPENAI_API_KEY
```

Then upgrade the release:

```bash
helm upgrade calculus-agent chart/ --reuse-values -n calculus-agent
```

The Deployment template injects the Secret value as an environment variable.
The `${OPENAI_API_KEY}` reference in `agent.yaml` picks it up at runtime
through normal env var substitution.

!!! note "Secrets vs ConfigMaps"
    Use ConfigMaps for non-sensitive configuration (`MODEL_ENDPOINT`,
    `LOG_LEVEL`). Use Secrets for credentials, API keys, and tokens. Secrets
    are base64-encoded at rest and can be encrypted with etcd encryption if
    your cluster is configured for it.

## MCP server authentication

The calculus-helper MCP server includes JWT authentication support in
`src/core/auth.py`. When enabled, the server validates a bearer token on every
request before executing any tool.

### Enable JWT auth on the MCP server

Set these environment variables on the MCP server deployment:

| Variable | Purpose |
|----------|---------|
| `MCP_AUTH_JWT_ALG` | Algorithm: `RS256`, `HS256`, etc. Auth is disabled if unset |
| `MCP_AUTH_JWT_SECRET` | Shared secret for HMAC algorithms |
| `MCP_AUTH_JWT_JWKS_URI` | JWKS endpoint URL (alternative to a static key) |
| `MCP_AUTH_JWT_ISSUER` | Expected `iss` claim in the token |
| `MCP_AUTH_JWT_AUDIENCE` | Expected `aud` claim in the token |

For HMAC-based auth (simplest to set up):

```bash
oc create secret generic mcp-auth \
  --from-literal=MCP_AUTH_JWT_SECRET=your-shared-secret \
  -n calculus-agent
```

Then add the env vars to the MCP server's Helm values:

```yaml
env:
  - name: MCP_AUTH_JWT_ALG
    value: HS256
  - name: MCP_AUTH_JWT_SECRET
    valueFrom:
      secretKeyRef:
        name: mcp-auth
        key: MCP_AUTH_JWT_SECRET
```

### Configure the agent for authenticated MCP

On the agent side, the MCP server entry in `agent.yaml` supports auth headers.
The agent passes a bearer token when connecting:

```yaml
mcp_servers:
  - url: ${MCP_CALCULUS_URL:-http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/}
    auth:
      token: ${MCP_AUTH_TOKEN}
```

Store the token in a Secret and inject it the same way as `OPENAI_API_KEY`.

!!! info "Production auth patterns"
    For production, prefer RS256 with a JWKS endpoint over shared secrets. This
    lets you rotate keys without redeploying. Set `MCP_AUTH_JWT_JWKS_URI` to
    your identity provider's JWKS URL (e.g., Keycloak or Red Hat SSO).

## Security configuration

The `security` section in `agent.yaml` controls runtime security behavior:

```yaml
security:
  mode: ${SECURITY_MODE:-enforce}
  tool_inspection:
    enabled: ${TOOL_INSPECTION_ENABLED:-true}
```

### Enforce vs observe mode

| Mode | Behavior | Use when |
|------|----------|----------|
| `enforce` | Blocks execution when a security finding is detected | Production |
| `observe` | Logs findings but allows execution to continue | Tuning and testing |

Start with `observe` when you first deploy to understand what the security
layer flags. Once you've reviewed the findings and confirmed they're legitimate,
switch to `enforce`.

### Tool inspection

When `tool_inspection.enabled` is `true`, the ToolInspector scans tool call
arguments for secrets, C2 patterns, and prompt injection before execution.
Findings are logged to `fipsagents.security.audit`. In `enforce` mode,
flagged calls are blocked; in `observe` mode, they are logged but allowed.

You can override the global mode per layer. For example, to enforce tool
inspection but only observe guardrails while tuning them:

```yaml
security:
  mode: enforce
  tool_inspection:
    enabled: true
  guardrails:
    mode: observe
```

## Resource limits and scaling

### Resource limits

The default Helm values set conservative resource limits because agents are
I/O-bound -- they spend most of their time waiting for LLM and MCP responses:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

Adjust these based on your agent's actual usage. An agent that processes large
context windows or runs heavy tool-result parsing may need more memory.

### Horizontal scaling

The agent and MCP server scale independently. Add a HorizontalPodAutoscaler
to scale the agent based on CPU utilization:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: calculus-agent
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: calculus-agent
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

Apply it with `oc apply -f hpa.yaml -n calculus-agent`. The same pattern works
for the MCP server -- create a separate HPA targeting its Deployment.

!!! warning "Apply HPA after your final Helm upgrade"
    The HPA takes ownership of `.spec.replicas` once applied. Any subsequent
    `helm upgrade` will conflict with the HPA over the replica count. Apply
    the HPA as the last step, after all Helm configuration is finalized. If
    you need to run `helm upgrade` later, delete the HPA first, upgrade, then
    re-apply.

!!! tip "Why min 2 replicas?"
    A single replica means any pod restart causes downtime. Two replicas
    ensure one pod is always available during rolling updates and restarts.

## Monitoring

### Health and readiness probes

The agent exposes `/healthz` for liveness probes. The Helm chart includes
probe definitions -- enable them in `values.yaml`:

```yaml
probes:
  enabled: true
```

This configures Kubernetes to restart the pod if `/healthz` stops responding
(liveness) and to stop routing traffic to it during startup (readiness).

### Pod logs

The most immediate debugging tool. Watch logs in real time:

```bash
oc logs deployment/calculus-agent -n calculus-agent -f
```

Key log patterns to watch for:

| Pattern | Meaning |
|---------|---------|
| `Uvicorn running on` | Agent started successfully |
| `Connected to MCP server` | MCP connection established |
| `Tool inspection finding` | Security layer flagged a tool call |
| `Retrying after error` | Backoff triggered on a failed LLM call |
| `Max iterations reached` | Agent hit the loop ceiling -- check `loop.max_iterations` |

Set `LOG_LEVEL` to `DEBUG` temporarily when investigating issues, then return
to `INFO` or `WARNING` for normal operation.

### Route timeouts

OpenShift Routes have a default timeout of 30 seconds. LLM calls regularly
exceed this, especially with large context windows. If you haven't already set
this in Module 5, annotate the agent's Route:

```bash
oc annotate route calculus-gateway \
  haproxy.router.openshift.io/timeout=120s \
  -n calculus-agent --overwrite
```

Do the same for the agent Route if it is also directly exposed. The UI Route
typically doesn't need a longer timeout since it serves static assets.

## Observability

The framework includes built-in observability features for production
deployments: session persistence, Prometheus metrics, structured trace
collection, and optional OpenTelemetry export. All are configured through
`agent.yaml` and share a common storage backend.

### Session persistence

Enable session persistence to maintain conversation continuity across
requests. Sessions are stored in the shared storage backend and expire
automatically.

```yaml
server:
  storage:
    backend: sqlite             # or: postgres
    sqlite_path: ./agent.db
  sessions:
    enabled: true
    max_age_hours: 168          # 7-day expiry
```

Override via Helm:

```bash
helm upgrade my-agent chart/ \
  --set config.STORAGE_BACKEND=sqlite \
  --set config.SESSIONS_ENABLED=true
```

The server exposes `POST /v1/sessions`, `GET /v1/sessions/{id}`, and
`DELETE /v1/sessions/{id}` for explicit session management. You can also
pass a `session_id` on any `ChatCompletionRequest` to auto-create the
session on first use. See the BaseAgent API reference for details.

### Prometheus metrics

The agent exposes Prometheus-format metrics at `GET /metrics`. Enable with:

```yaml
server:
  metrics:
    enabled: true
```

Requires the `[metrics]` extra: `pip install fipsagents[metrics]`.

Available metrics:

| Metric | Type | Labels |
|--------|------|--------|
| `agent_requests_total` | counter | model, status, stream |
| `agent_request_duration_seconds` | histogram | model |
| `agent_model_call_duration_seconds` | histogram | model |
| `agent_tool_call_total` | counter | tool_name, status |
| `agent_tokens_total` | counter | model, direction |

To scrape metrics with OpenShift user-workload monitoring, create a
ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-agent-metrics
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: my-agent
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### Trace collection

TraceCollector records structured spans for every request -- model calls,
tool invocations, and durations. Enable traces alongside storage:

```yaml
server:
  storage:
    backend: sqlite
  traces:
    enabled: true
    sampling_rate: 1.0
```

Query traces via `GET /v1/traces` and `GET /v1/traces/{id}`. Each trace
includes duration, span count, tool calls, and the model used. See the
BaseAgent API reference for the full trace schema.

### OTEL export (optional)

For enterprise observability stacks, export traces to an OpenTelemetry
Collector via OTLP:

```yaml
server:
  traces:
    enabled: true
    exporter: otel
    otel_endpoint: http://otel-collector:4317
    service_name: my-agent
```

Requires the `[otel]` extra: `pip install fipsagents[otel]`.

The server automatically propagates W3C Trace Context (`traceparent`
header) -- extracting it from incoming requests and injecting it into
outgoing RemoteNode calls. This links spans across multi-agent workflows
into a single distributed trace without any application-level code.

### User feedback collection

Metrics tell you the agent is fast. Traces tell you what it did. Neither
tells you whether users were happy with the answer. Feedback collection
closes that gap by storing thumbs-up / thumbs-down ratings, optional
comments, and corrections -- joined to the trace that produced each
response so you can replay the conversation behind a bad rating.

This data is the raw material for two downstream pipelines: dashboards
that surface degradations early, and labelled datasets for fine-tuning
or RLHF.

Enable feedback alongside tracing:

```yaml
server:
  storage:
    backend: sqlite             # or: postgres
  traces:
    enabled: true               # so feedback can join to a trace
  feedback:
    enabled: true
    max_age_hours: 720          # keep 30 days
```

Override via Helm or env vars:

```bash
helm upgrade my-agent chart/ \
  --set config.STORAGE_BACKEND=sqlite \
  --set config.TRACES_ENABLED=true \
  --set config.FEEDBACK_ENABLED=true
```

#### REST endpoints

The server exposes four feedback endpoints:

| Path | Method | Purpose |
|------|--------|---------|
| `/v1/feedback` | POST | Submit a rating (1 = thumbs-up, -1 = thumbs-down) |
| `/v1/feedback` | GET | Query records, filterable by `trace_id`, `session_id`, time window |
| `/v1/feedback/{feedback_id}` | PATCH | Edit an existing record in place — change the rating, revise the comment |
| `/v1/feedback/stats` | GET | Aggregated counts grouped by time window (`hour` / `day` / `week`) |

A minimal POST looks like this:

```bash
curl -X POST http://my-agent:8080/v1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"trace_id":"trace_abc123","rating":1,"comment":"clear explanation"}'
```

`trace_id` is optional -- if omitted, the server synthesises a stand-alone
identifier so feedback works even when tracing is disabled or sampled
out. Records keyed to a real trace can be joined to the trace store;
orphan records are still useful as raw rating data.

When a user changes their mind on an already-rated message, send a PATCH
with the new fields rather than posting again -- the record updates in
place, no duplicate row is created. PATCH bodies are partial: omitted
fields stay as they were.

```bash
# Capture the feedback_id from the original POST response, then:
curl -X PATCH http://my-agent:8080/v1/feedback/fb_abc123 \
  -H 'Content-Type: application/json' \
  -d '{"rating":-1,"comment":"on second look, this was wrong"}'
```

Returns 200 with the full updated record, or 404 if the id is unknown.

#### Where the trace_id comes from

Every chat completion response now carries an `X-Trace-Id` header (sync
and streaming) and a top-level `trace_id` field on the final SSE usage
chunk. UI clients capture either value and attach it to subsequent
feedback POSTs. The gateway preserves the value verbatim:

```
Browser  ──POST /v1/feedback──▶  UI proxy  ──▶  Gateway  ──▶  Agent
                                                  └─ forwards Authorization,
                                                     X-User-ID for attribution
```

#### UI integration

The chat UI scaffolded by `fips-agents create ui` includes thumbs-up /
thumbs-down icons that hover-reveal on completed assistant messages.
Thumbs-up records a positive rating immediately. Thumbs-down opens a
small modal asking for a category (Inaccurate / Not helpful / Harmful /
Too long / Other) plus an optional free-text comment, then POSTs to
`/v1/feedback` via the gateway. Categories are encoded as a bracketed
prefix on the comment field (`[Inaccurate] verbose detail`) so they
round-trip through the existing schema and remain recoverable from
queries.

#### Querying feedback

List the most recent records for a session:

```bash
curl 'http://my-agent:8080/v1/feedback?session_id=demo-1&limit=20' | jq
```

Get aggregated stats for the last 7 days, bucketed by day:

```bash
curl 'http://my-agent:8080/v1/feedback/stats?window=day&since=2026-04-19T00:00:00Z' | jq
```

Each stats row contains `window_start`, `window_end`, `agent_type`,
`thumbs_up`, `thumbs_down`, and `total`. Pipe these to your analytics
stack -- a Grafana panel keyed off the SQLite or Postgres backend is
typical.

#### Lab exercise

Enable feedback on the calculus agent with sqlite storage:

1. Set `server.feedback.enabled: true` and `server.storage.backend: sqlite`
   in `agent.yaml`.
2. Add `fipsagents[feedback]` to the `dependencies` list in
   `pyproject.toml` (or run `pip install 'fipsagents[feedback]'` in your
   venv).
3. Redeploy: `make deploy PROJECT=calculus-agent`.
4. Open the chat UI, run several conversations, click thumbs-up on good
   answers and thumbs-down (with a category) on bad ones.
5. Query `/v1/feedback/stats?window=hour` to see your ratings aggregated.
6. Pick a low-rated trace and fetch it: `GET /v1/traces/{trace_id}` -- the
   full conversation, tool calls, and timings are recoverable. That is
   your first labelled training example.

## What's next

You've built and hardened a complete AI agent system across eight modules:

1. **Scaffolded** an agent project and understood every file
2. **Configured** the agent for a real LLM and deployed it to OpenShift
3. **Built** an MCP server with calculus tools
4. **Wired** the MCP tools into the agent
5. **Deployed** a gateway and chat UI for browser-based interaction
6. **Added** a code execution sandbox for numerical computation
7. **Extended** the agent with AI-assisted slash commands
8. **Hardened** the stack with secrets, authentication, security policy, monitoring, observability, and user feedback collection

The `calculus-agent/` and `calculus-helper/` directories in this repository
serve as complete reference implementations. Use them as starting points for
your own agents.

For deeper dives into specific topics, see the [Reference](index.md#reference)
pages: agent.yaml configuration, Helm chart anatomy, BaseAgent API, and MCP
protocol details.

When you're ready to teach the agent to read user-supplied documents,
[Module 9](09-file-uploads.md) covers the file-upload track end-to-end:
drag-drop UI, streaming gateway proxy, Docling parsing, and ClamAV virus
scanning.
