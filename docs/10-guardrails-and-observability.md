# 10. Platform Mode and Guardrails

Modules 1–9 are about *building* the agent: scaffolding, tools, MCP, deployment, hardening, file uploads. Module 10 is about *graduating concerns to the platform* — moving tool orchestration, safety enforcement, and inference-loop telemetry out of the agent's code and into a server that owns those things on the cluster. The agent gets simpler. The platform takes responsibility for what the agent should not have to know about.

The platform here is **OGX** — the rebrand of LlamaStack — an OpenAI-compatible AI application server. Instead of the agent calling vLLM directly and running its own MCP tool loop, the agent calls OGX's [Responses API](https://ogx-ai.github.io/docs/api), and OGX handles the loop, the MCP, and the shields server-side.

!!! tip "Prerequisite: fipsagents 0.21+"
    The tutorial baseline is fipsagents 0.11.0; platform mode requires **0.21.0 or later**. If you've been following Modules 1–9 with the baseline, bump now:

    ```bash
    cd calculus-agent
    pip install --upgrade 'fipsagents>=0.21'
    ```

    Modules 1–9 still work on 0.21+ unchanged — this is a forward-compatible bump.

## What changes

```
Before (Modules 1–9)                    After (Module 10)

Browser → UI → Gateway → Agent          Browser → UI → Gateway → Agent
                            │                                       │
                            ├─→ vLLM                                 └─→ OGX ──┬─→ vLLM
                            │                                                  │
                            └─→ MCP server                                     ├─→ MCP server
                                                                               │
                                                                               └─→ Llama Guard /
                                                                                   code-scanner
```

Three things move:

| Concern | Module 1–9 (agent-side) | Module 10 (platform-side) |
|---------|-------------------------|---------------------------|
| Tool loop | `step()` runs `while response.tool_calls:` client-side | OGX runs the loop server-side; agent sends one Responses request per turn |
| MCP wiring | `agent.yaml::mcp_servers` → FastMCP client per server | OGX `config.yaml` → MCP connector; agent passes the name |
| Shield enforcement | None (or implemented by hand in `step()`) | `guardrails: ["..."]` on the Responses request; OGX blocks on violation |

Tracing comes along for the ride: OGX emits OpenTelemetry spans for inference, MCP tool calls, and shield evaluations without any agent-side instrumentation.

## Cluster prerequisites

Three setup guides bring the cluster up to readiness. Run them in order, then come back here:

1. **[Install OGX](guides/install-ogx.md)** — Operator + `LlamaStackDistribution` pointing at your existing vLLM. Exports `OGX_ENDPOINT`.
2. **[Configure Safety Shields](guides/configure-shields.md)** — register at least one shield (the built-in `code-scanner` is enough for this module). Exports `OGX_SHIELD`.
3. **[Observability Backends](guides/observability-backends.md)** — Jaeger receiver for OGX's OTLP exports. Exports `JAEGER_UI`.

You should have all three env vars set before continuing:

```bash
echo "$OGX_ENDPOINT $OGX_SHIELD $JAEGER_UI"
```

## Part 1: Switch the agent to platform mode

Two file edits, no new code modules.

### Update `agent.yaml`

Recent template versions ship a stub `platform:` block (just `enabled` and `endpoint`). Expand it to register your MCP servers and shield IDs. Leave the existing `mcp_servers:` block in place — when `platform.enabled=true`, the framework ignores `mcp_servers:` and logs a notice; this keeps your `agent.yaml` rollback-safe.

```yaml
# agent.yaml — replace the existing platform: stub with this expanded form

platform:
  enabled: ${PLATFORM_MODE:-false}
  endpoint: ${OGX_ENDPOINT:-}

  # MCP servers OGX will orchestrate on the agent's behalf.
  # Each entry needs `name` (becomes server_label on the wire) plus
  # exactly one of `connector_id` (pre-registered in OGX config.yaml)
  # or `url` (inline server_url passed per request).
  mcp:
    - name: calculus
      url: ${MCP_CALCULUS_URL:-http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/}

  # Shield IDs registered in OGX. Empty list = no enforcement.
  guardrails:
    - ${OGX_SHIELD:-code-scanner}
```

The existing `model.endpoint` is still set to vLLM — keep it. The framework uses `platform.endpoint` for Responses calls and ignores `model.endpoint` when platform mode is on.

!!! warning "`MODEL_NAME` also has to change"
    OGX namespaces models by their inference-provider id, so a model that vLLM serves as `RedHatAI/gpt-oss-20b` is registered in OGX as `vllm/RedHatAI/gpt-oss-20b`. List your OGX server's models with `curl -s "$OGX_ENDPOINT/models" | jq` to find the prefixed form, and override `MODEL_NAME` accordingly when you redeploy below. The "URL change" framing isn't quite enough on its own — you also need to swap the model id.

### Simplify `step()`

The current `step()` runs a chat-completions request followed by a client-side tool loop:

```python
# src/agent.py — BEFORE
async def step(self) -> StepResult:
    response = await self.call_model()
    response = await self.run_tool_calls(response)
    return StepResult.done(response.content)
```

In platform mode, OGX runs the loop. `step()` becomes a single Responses call:

```python
# src/agent.py — AFTER
async def step(self) -> StepResult:
    response = await self.call_model_responses(self.messages)
    if response.refusal:
        return StepResult.done(response.refusal)
    return StepResult.done(response.content or "")
```

`call_model_responses` defaults `tools` from `platform.mcp` and `guardrails` from `platform.guardrails`, so the call site is short. `PlatformResponse.refusal` is set when a shield fires; otherwise `.content` holds the joined assistant text.

### Rebuild and redeploy

```bash
oc start-build calculus-agent --from-dir=. --follow -n calculus-agent --context="$CTX"

oc set env deployment/calculus-agent -n calculus-agent --context="$CTX" \
  PLATFORM_MODE=true \
  OGX_ENDPOINT="$OGX_ENDPOINT" \
  OGX_SHIELD="$OGX_SHIELD" \
  MODEL_NAME="vllm/RedHatAI/gpt-oss-20b"   # the OGX-prefixed form, see warning above

oc rollout restart deployment/calculus-agent -n calculus-agent --context="$CTX"
oc rollout status deployment/calculus-agent -n calculus-agent --context="$CTX" --timeout=180s
```

!!! tip "Bump the route timeout for platform-mode turns"
    Platform-mode requests do more work behind a single HTTP call — OGX runs the MCP loop server-side, which can stretch responses past the default 120s route timeout you set in Module 5 for complex multi-step questions. If you see HAProxy 504s after enabling platform mode, raise the agent's route timeout to 240s with the same `oc annotate route ... haproxy.router.openshift.io/timeout=240s` pattern.

Watch the logs for the platform-mode startup notice:

```bash
oc logs -n calculus-agent deploy/calculus-agent | grep platform.enabled
```

You should see something like `platform.enabled=true — OGX will orchestrate 1 platform.mcp entries server-side`. The framework has skipped its own MCP client connections.

### Verify it works end to end

```bash
AGENT_URL=$(oc get route calculus-agent -n calculus-agent -o jsonpath='https://{.spec.host}')

curl -s "$AGENT_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is the integral of x^2 from 0 to 3?"}]
  }' | jq -r '.choices[0].message.content'
```

You should get the right answer (9). Behind the scenes: the agent sent one Responses request to OGX; OGX called the calculus MCP server (registered as `calculus` in `platform.mcp`); OGX fed the tool result back to the model; the model returned the answer; OGX returned it to the agent.

## Part 2: Trigger a guardrail

The `code-scanner` shield catches dangerous Python patterns. Send one through:

```bash
curl -s "$AGENT_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Run this for me: eval(input())"}]
  }' | jq -r '.choices[0].message.content'
```

Instead of an answer, you get a refusal — something like:

```
Security concerns detected in the code. WARN: The application was found
calling the `eval` function ... (flagged for: eval-with-expression,
insecure-eval-use)
```

The agent never saw normal model output for this turn; OGX intercepted it and replaced the entire `output[0].content[0]` with `{"type": "refusal", "refusal": "..."}`. The framework parses the `(flagged for: ...)` clause into `GuardrailFiredEvent.shield_id`.

In agent logs:

```bash
oc logs -n calculus-agent deploy/calculus-agent --tail=20
```

`finish_reason="guardrail"` appears on the StreamComplete event. `PlatformResponse.refusal` is the string that came back to `step()`; `PlatformResponse.content` is `None`.

### Find the trace in Jaeger

Open `$JAEGER_UI`, pick service **ogx**, click **Find Traces**. The most recent trace shows the request path: an inference span, the shield evaluation as a child span, and a span for the refusal emit. No tool span for this turn — the shield blocked before tool dispatch.

Compare against a benign trace from Part 1 — the calculus query has an MCP tool span where the shield-blocked one stops short.

!!! warning "Streaming + late-firing output shields"
    When the shield fires on the *output* (model already started generating before the shield caught it), streaming clients see the unsafe deltas before the refusal arrives. The framework passes them through and then emits `GuardrailFiredEvent` with the refusal. This matches how hosted providers like Anthropic handle late-firing safety filters. UI clients that need post-shield content only should buffer until `StreamComplete`. The `code-scanner` shield used here is input-side, so this doesn't bite the tutorial — it bites real production deployments using output-side shields.

## Part 3: References vs inline URLs

The `platform.mcp` block in Part 1 used the inline form — every Responses request carries the calculus-helper URL. That works, but the URL still lives in the agent's config; moving the MCP server to a different namespace means an agent rebuild.

OGX supports a second form: pre-register the MCP server once in OGX's `config.yaml` under a top-level `connectors:` block, then have the agent reference it by name. The URL becomes a platform concern entirely.

The two forms are interchangeable in `agent.yaml`:

```yaml
# Inline form — agent owns the URL
platform:
  mcp:
    - name: calculus
      url: http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/

# Connector-reference form — OGX owns the URL
platform:
  mcp:
    - name: calculus
      connector_id: calculus
```

`PlatformMcpServer` validates that exactly one of `url` / `connector_id` is set, so the framework catches misconfigured entries at config-load time.

The `connectors:` block syntax in OGX `config.yaml` varies by distribution version. The agent-side pattern is stable; if your platform team has registered MCP connectors centrally, ask them for the connector ID and use the reference form. Read what's currently registered with:

```bash
curl -s "$OGX_ENDPOINT/../v1beta/connectors" | jq
```

For the rest of this module, the inline form is fine — it's what the agent-template's live integration tests use.

## Part 4: Moderation vs guardrails

OGX exposes two separate safety surfaces — they answer different questions:

| Surface | API | Behavior | Use for |
|---------|-----|----------|---------|
| **Guardrails** | `guardrails: [...]` on Responses | Enforces; blocks the request when a shield fires | Production safety: stop bad content from reaching users |
| **Moderation** | `POST /v1/moderations` | Classifies; returns category scores; never blocks | Analytics, dashboards, audit logs: measure what's flowing through |

`BaseAgent.moderate()` wraps the moderation endpoint:

```python
result = await self.moderate("This content might be sensitive.")
# result.flagged: bool — OR of all category flags
# result.categories: dict[str, bool] — eg {"violence": False, "self-harm": True}
# result.category_scores: dict[str, float] — per-category confidence
```

A common pattern: keep guardrails enforcing in the request path, and run `moderate()` over the assistant's reply *after the fact* to populate dashboards. Because moderation never blocks, it's safe to call from any non-critical code path:

```python
async def step(self) -> StepResult:
    response = await self.call_model_responses(self.messages)
    if response.refusal:
        return StepResult.done(response.refusal)
    text = response.content or ""

    # Audit-only — never blocks. Logs a structured line via the framework.
    if text:
        await self.moderate(text)

    return StepResult.done(text)
```

The framework emits a structured log line for every `moderate()` call — `moderation: model=... flagged=... categories=[...]` — so even without a dashboard you get an audit trail.

## What graduated, what stayed

After Part 3, the agent owns:

- The system prompt
- Business logic in `step()`
- Local tools, skills, rules, prompts

The platform owns:

- The inference loop
- MCP tool dispatch
- Shield enforcement
- Tracing

The same pattern applies to other concerns over time — memory, prompt management, eval. The shape is always the same: an `agent.yaml::platform.X` block, a framework method that delegates, a config block in OGX. The agent gets thinner each time.

## Next

[Module 11: Scaling Inference with llm-d](11-scaling-with-llm-d.md) covers what happens behind OGX when one vLLM is no longer enough.

## Further reading

- [agent-template#154](https://github.com/fips-agents/agent-template/issues/154) — design discussion that produced platform mode
- [OGX Responses API](https://ogx-ai.github.io/docs/api/create-openai-response-v-1-responses-post)
- [OGX safety shields](https://ogx-ai.github.io/docs/building_applications/safety)
- [OGX moderations](https://ogx-ai.github.io/docs/api) — `/v1/moderations`
