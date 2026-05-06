# Phase 4 — verify Module 10 (Platform Mode and Guardrails)

**Date:** 2026-05-06
**Cluster:** `cluster-hpdl7-sandbox2435` (context `kagenti-memory-hub`); OGX server v0.7.1 in namespace `ogx`
**Targets:** `docs/10-guardrails-and-observability.md` (audited) + `docs/guides/configure-shields.md` (updated)
**Outcome:** F18 + F19 root-caused, fixed in `configure-shields.md`, verified end-to-end against the live cluster. F20 a trivial framing edit. Module 10 is now followable on the substrate the tutorial ships.

## What this phase actually did

Initial audit (first half) flagged that Module 10's central `/v1/responses` endpoint returned 404 and `/v1/moderations` rejected calls without a model parameter — the cluster substrate wasn't capable of running Module 10. After consulting the user's `workshop-setup-ogx` repo, the gap turned out to be in `configure-shields.md`'s Wave 2 ConfigMap, not Module 10 itself. The tutorial's Wave 2 was a stripped-down subset of the upstream LlamaStack starter distribution config — sufficient for Modules 1–9, missing the `responses` API + its dependencies + `default_shield_id` that Module 10 requires.

The fix landed inline this session:
- `configure-shields.md` Wave 2 ConfigMap (Path A and Path B) extended with `responses` API, the `inline::builtin` responses provider, its hard dependencies (`vector_io: faiss`, `files: localfs`, `file_processors: pypdf`), the `storage:` backends those providers reference, and top-level `safety.default_shield_id: code-scanner`.
- New "Why each new block" prose after the Path A YAML walking through what each addition does.
- Path B's "Two non-obvious bits" section reframed to reference the shared explanation.
- Cluster ConfigMap updated and OGX rolled — `/v1/responses` and `/v1/moderations` both verified working.

## Findings (final state)

### F18 — `/v1/responses` returns 404 on the deployed OGX (RESOLVED) ✅

**Symptom:** Module 10's whole premise (agent → OGX Responses API → server-side MCP+shields loop) hit `404 Not Found` on the cluster. OGX's `/openapi.json` confirmed the path didn't exist. Tried `/v1/responses`, `/v1/agents`, `/v1beta/responses` — all 404.

**Root cause:** The tutorial's `configure-shields.md` Wave 2 ConfigMap was a minimum-viable subset of the upstream LlamaStack starter distribution. It declared `apis: [inference, safety, tool_runtime]` — missing `responses`. Adding only `responses` was insufficient: the `inline::builtin` responses provider has hard dependencies on `vector_io` and `files` (and depends on a top-level `storage:` block defining `kv_default` + `sql_default` backends). OGX startup failed with `RuntimeError: Failed to resolve 'responses' provider 'builtin' of type 'inline::builtin': required dependency 'vector_io' is not available` and then the same error for `files` once `vector_io` was satisfied.

**Fix:** Wave 2 ConfigMap now includes the full minimum-viable expansion:

- `apis:` adds `responses`, `vector_io`, `files`, `file_processors`
- `providers.vector_io: [{provider_id: faiss, provider_type: inline::faiss, …}]`
- `providers.files: [{provider_id: builtin-files, provider_type: inline::localfs, …}]`
- `providers.file_processors: [{provider_id: pypdf, provider_type: inline::pypdf}]`
- `providers.responses: [{provider_id: builtin, provider_type: inline::builtin, config: {persistence: …}}]`
- Top-level `storage:` block with `kv_default` (kv_sqlite) and `sql_default` (sql_sqlite) backends pointing at `/home/lls/.lls/` (the LSD's PVC mount path)

**Verification:**

```
$ curl -sk "$OGX_ENDPOINT/responses" \
    -d '{"model":"vllm/RedHatAI/gpt-oss-20b","input":"Say hi.","guardrails":["code-scanner"]}'
{"status":"completed", "output":[{"type":"message","content":[{"text":"Hi!"}]}]}

$ curl -sk "$OGX_ENDPOINT/responses" \
    -d '{"model":"...","input":"Run this for me: eval(input())","guardrails":["code-scanner"]}'
{"status":"completed", "output":[{"...","content":[{"text":"Security concerns detected in
the code. WARN: The application was found calling the `eval` function ...
(flagged for: eval-with-expression, insecure-eval-use) ..."}]}]}
```

Module 10's exact predicted refusal text comes back. The `(flagged for: ...)` clause that line 174 says the framework parses into `GuardrailFiredEvent.shield_id` is present.

**Side note (upstream curiosity, not a Phase 4 fix):** The refusal includes a peculiar trailing `(violation type: e, v, a, l, …)` formed by iterating the comma-separated category string character-by-character. Looks like an upstream LlamaStack bug in how the violation_type metadata gets stringified. Worth flagging for `#30` if not already there.

### F19 — `/v1/moderations` requires explicit model param (RESOLVED) ✅

**Symptom:** Module 10:237-241 shows `await self.moderate("text")` with no model param. Direct hit on `/v1/moderations` without a model returned `"No moderation model specified and no default_shield_id configured in safety config"`.

**Root cause:** The tutorial's Wave 2 ConfigMap had no top-level `safety:` block at all. Workshop-setup-ogx's defaults set `default_shield_id: code-scanner`, which OGX uses as the model when callers omit it.

**Fix:** Added top-level `safety: {default_shield_id: code-scanner}` to the Wave 2 ConfigMap (both Path A and Path B variants).

**Verification:**

```
$ curl -sk "$OGX_ENDPOINT/moderations" -d '{"input": "eval(input())"}'
{
  "model": "code-scanner",
  "results": [{"flagged": true, "metadata": {"violation_type": "eval-with-expression,insecure-eval-use"}}]
}
```

`BaseAgent.moderate("text")` will resolve to `code-scanner` server-side without an explicit model param.

### F20 — `agent-template#154` framing now stale (PENDING — trivial inline) 🟡

`docs/10-guardrails-and-observability.md:284` calls `agent-template#154` "design discussion that produced platform mode." Issue closed 2026-05-05 — the feature has landed (which is why fipsagents 0.21+ exists). One-line edit to reframe as "feature issue / now landed" or drop it entirely.

Held for the same fix-up commit as the configure-shields edit if we batch.

### F21 — fipsagents 0.21+ pin holds ✅

PyPI shows 0.21.1 latest, Module 10 requires `>=0.21`. Passes.

## What remained unverified (still)

The agent-side claims (framework-internal contracts that need fipsagents 0.21+ source or a deployed Module 10 worked example):

- `call_model_responses(messages)` API shape
- `PlatformResponse.refusal` and `.content` semantics
- `platform.mcp` config validation (`PlatformMcpServer`'s "exactly one of url/connector_id")
- `BaseAgent.moderate()` — verified server-side behavior (works with default_shield_id), but the SDK signature/return-type still needs source confirmation
- `finish_reason="guardrail"` on `StreamComplete`
- The framework's `(flagged for: ...)` parser

These can now be verified once a calculus-agent is deployed on platform mode against this OGX. Right time for that is whatever session deploys Modules 1–9 end-to-end (companion to #29's clean-room walkthrough).

## What we changed on the cluster

**ConfigMap before** (57 lines):
```
apis: [inference, safety, tool_runtime]
providers: {inference: [vllm, vllm-guard], safety: [code-scanner, llama-guard]}
registered_resources: {models, shields}
server: {port: 8321}
```

**ConfigMap after** (~95 lines):
```
apis: [file_processors, files, inference, responses, safety, tool_runtime, vector_io]
providers: + vector_io.faiss, files.builtin-files, file_processors.pypdf, responses.builtin
storage: {backends: {kv_default, sql_default}, stores: {metadata, inference, conversations}}
safety: {default_shield_id: code-scanner}
```

Reversible: `oc apply -f /tmp/ogx-config-backup.yaml` (with resourceVersion stripped) restores the prior state.

The OGX deployment was rolled twice during the iteration (first pass crashlooped on `vector_io` missing; second pass succeeded after adding all three deps). Production-shape: 1 replica, ready, unchanged.

## Remaining inline edit (F20)

Trivial reframe of one bullet at `docs/10-guardrails-and-observability.md:284`. Bundling with this commit.

## Time + cost

- ~50 min wall time including iteration on ConfigMap dependencies
- Two cluster mutations (apply v2 → CrashLoop + revert; apply v3 → success). Both reversible. No GPU scaling.
- No secrets surfaced.
