# install-ogx test — findings

Cluster test of a corrected `install-ogx.md` draft against the kagenti-memory-hub cluster, against vLLM serving `RedHatAI/gpt-oss-20b` via KServe `InferenceService`. End state: OGX successfully proxying chat completions through to vLLM.

**Outcome:** the verified draft was promoted to [`docs/guides/install-ogx.md`](../../docs/guides/install-ogx.md). The accompanying `serve-an-llm.md` was rewritten in the same iteration (gpt-oss-20b switch + RHOAI 3.x Headless URL caveat). Working manifests retained under `manifests/` for reference.

**Wave 2 follow-up — `configure-shields.md`:** rewritten to extend the same `ogx-config` ConfigMap with `safety` API, `inline::code-scanner` provider, and a `code-scanner` shield. Path A (code-scanner) tested end-to-end on the cluster: `/v1/shields` returns the registered shield, `POST /v1/safety/run-shield` fires on `eval(input())` with `violation_type: "eval-with-expression,insecure-eval-use"` and returns null on benign content, chat completions through OGX still work. Path B (Llama Guard) was rewritten with the corrected vLLM patterns from `serve-an-llm.md` but **was not tested end-to-end** — the cluster has only one GPU and it's allocated to the gpt-oss-20b backend. Wave 2 manifest archived as `manifests/ogx-config-wave2.yaml`.

**Sweep edits (consistency):** four other docs referenced the old `OGXDistribution` / granite-3.3-8b patterns and were updated in the same pass:

- `docs/00-prerequisites.md` — switched section heading + body to gpt-oss-20b
- `docs/10-guardrails-and-observability.md` — `OGXDistribution` → `LlamaStackDistribution` in the prereq list
- `docs/11-scaling-with-llm-d.md` — same rename in the A/B-test paragraph
- `docs/guides/observability-backends.md` — three replacements (`OGXDistribution` → `LlamaStackDistribution`, `oc edit ogxdistribution` → `oc edit llamastackdistribution`, granite model name → `vllm/RedHatAI/gpt-oss-20b` plus `max_tokens` so the reasoning trace doesn't truncate)

**Telemetry / observability — env-var-only approach is correct, no ConfigMap needed.** Initial worry that `observability-backends.md` needed Wave-2-style ConfigMap treatment turned out to be wrong, traceable to outdated info in the early Explore-agent recipe. In OGX v0.7.1 telemetry is **built-in**, not a `config.yaml` provider — `llama_stack/telemetry/__init__.py` reads standard OpenTelemetry env vars at startup and configures exporters from there. The bundled starter `config.yaml` has no `telemetry` in `apis` or `providers` — confirmed by `cat`-ing it from inside the running pod.

E2E test on the cluster surfaced three real bugs in the existing doc and one fundamental v0.7.1 limitation that needs a workaround:

1. **Service name mismatch.** Doc claimed traces appear under service `ogx` in Jaeger, but the SDK default is `llama-stack`. Setting `OTEL_SERVICE_NAME=ogx` alongside `OTEL_EXPORTER_OTLP_ENDPOINT` makes the doc's promise true.
2. **Stale Jaeger image tag.** Doc pinned `jaegertracing/all-in-one:1.62`, which never existed (Docker Hub's tag list starts at `1.63.0`; current is `1.76.0`). Updated to `1.76.0`.
3. **`setup_telemetry()` only initializes `MeterProvider`, not `TracerProvider`.** Routers do `from opentelemetry import trace` and create spans (visible in `core/routers/safety.py`, `core/routers/inference.py`, etc.), but with no `TracerProvider` set, those spans go to the no-op default tracer and are discarded. Result: setting `OTEL_EXPORTER_OTLP_ENDPOINT` alone gives you metrics export only — Jaeger ingests traces (not metrics), so the UI stays empty.

   **Workaround that worked:** override the container entrypoint to wrap with `opentelemetry-instrument`, which auto-configures both providers. The starter image already ships `opentelemetry-distro` + the relevant instrumentation packages.

   ```yaml
   spec:
     server:
       containerSpec:
         command: ["opentelemetry-instrument"]
         args:
           - uvicorn
           - llama_stack.core.server.server:create_app
           - --host
           - "0.0.0.0"
           - --port
           - "8321"
           - --workers
           - "1"
           - --factory
         env:
           - name: OTEL_EXPORTER_OTLP_ENDPOINT
             value: "http://jaeger.observability.svc.cluster.local:4318"
           - name: OTEL_SERVICE_NAME
             value: "ogx"
           - name: OTEL_TRACES_EXPORTER
             value: "otlp"
           - name: OTEL_EXPORTER_OTLP_PROTOCOL
             value: "http/protobuf"
   ```

   With the wrapper in place, Jaeger's `/api/services` returns `ogx` and `/api/traces?service=ogx` returns spans named `POST /v1/chat/completions`, `POST /v1/safety/run-shield`, `chat RedHatAI/gpt-oss-20b` (OGX-internal), `connect` (httpx outbound to vLLM), `INSERT /root/.llama/distributions/sql_store.db` (sqlite3 instrumentation), and asgi `http send/receive` spans. Doc rewritten to show this override and to flag that it should become unnecessary once upstream adds a `TracerProvider` to `setup_telemetry()`.

   This is the most upstream-issue-worthy of all the findings in this iteration. Open it against `meta-llama/llama-stack` (or `ogx-ai/ogx-k8s-operator` if they prefer to bundle the wrapper into the image's entrypoint).

## Summary of drift caught beyond what `workshop-setup-ogx` already documents

### 1. Wave 1 ("no userConfig") is not viable for tutorial use

The starter image at `docker.io/llamastack/distribution-starter:0.7.1` bundles a `config.yaml` whose `registered_resources.models: []` is hardcoded empty. The `VLLM_INFERENCE_MODEL` env var is **not** read by the bundled config. And OGX v0.7.1 has **no runtime model-registration endpoint** (`POST /v1/models` returns 405; only `GET /v1/models` and `GET /v1/models/{id}` are exposed per `/openapi.json`).

Net result: with no userConfig, OGX serves only the bundled embedder + reranker (`nomic-embed-text-v1.5`, `Qwen3-Reranker-0.6B`). Chat completions return 404 because no LLM is registered.

**Implication for the doc:** the Wave 1 / Wave 2 split has to shift. Wave 1 must include a minimal `userConfig` ConfigMap that registers the LLM. Wave 2 (= `configure-shields.md`) extends that same ConfigMap with shields, vector DBs, and MCP connectors.

A 12-line ConfigMap is enough for Wave 1 — `apis: [inference, tool_runtime]`, one vLLM provider, one model, empty shields/tool_groups, and `server.port: 8321`. Tested on cluster.

### 2. `VLLM_URL` must include `/v1`

The Explore agent's recipe report stated:

> `VLLM_URL`: base URL (no trailing `/v1`)

This is wrong. The starter `config.yaml` sets `base_url: ${env.VLLM_URL:=}` literally, and the OpenAI client OGX uses internally then POSTs to `<base_url>/chat/completions` — vLLM serves under `/v1/chat/completions`, so without the suffix you get HTTP 404 from vLLM (which surfaces in OGX as `openai.NotFoundError`).

The playbook's `vars/mcp-rhoai.yml` has `ogx_vllm_url: "http://gpt-oss-20b.gpt-oss-model.svc.cluster.local/v1"` — `/v1` is included. Trust the playbook over the recipe summary.

### 3. The vLLM provider config field is `base_url:`, not `url:`

The original (pre-corrected) `install-ogx.md` and the Explore agent's CR sketch both used `url:`. The starter v0.7.1 `config.yaml` actually uses `base_url:`. Visible by inspection inside the running pod at `/usr/local/lib/python3.12/site-packages/llama_stack/distributions/starter/config.yaml`.

### 4. With KServe `rawDeploymentServiceConfig: Headless`, the in-cluster URL needs the targetPort

This cluster's RHOAI DSC is configured with `kserve.rawDeploymentServiceConfig: Headless`. KServe creates the predictor Service with `ClusterIP: None`, which means DNS resolves directly to pod IPs and the Service's `port: 80 → targetPort: 8000` mapping doesn't apply. You must hit the pod's listening port — `:8000` — directly.

The `InferenceService.status.url` reports the URL **without** the port (`http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local`), which is misleading. Confirmed: `curl http://...svc.cluster.local/v1/models` → connection refused; `curl http://...svc.cluster.local:8000/v1/models` → HTTP 200.

**Implication:** `serve-an-llm.md` should call out the Headless-vs-non-Headless URL pattern, since `install-ogx.md` consumes `MODEL_ENDPOINT` from there. Either:
- Document both patterns and tell readers to check `oc get svc <predictor> -o jsonpath='{.spec.clusterIP}'` (`None` → use targetPort), or
- Recommend cluster operators set `rawDeploymentServiceConfig` to a non-Headless mode and use port 80 throughout.

### 5. Service name suffix: `<distribution-name>-service`

The operator names the downstream Service `<metadata.name>-service`. With `name: ogx`, the Service is `ogx-service`, not `ogx`. Both the in-cluster URL and the `oc create route --service=...` command needed updating.

The CR's `.status.serviceURL` reports the correct value — recommend the doc print it for the reader to copy.

### 6. Models are exposed as `<provider_id>/<model_id>`, not bare `<model_id>`

Registering with `model_id: RedHatAI/gpt-oss-20b, provider_id: vllm` causes OGX to advertise the model as `vllm/RedHatAI/gpt-oss-20b` in `/v1/models`. Querying with the bare `RedHatAI/gpt-oss-20b` returns 404 because OGX splits on `/` to find a provider named `RedHatAI`.

**Implication for Module 10:** the agent's `MODEL_NAME` env var in platform mode is **not** the same value as in Modules 1–9. If Modules 1–9 use `MODEL_NAME=ibm-granite/granite-3.3-8b-instruct` for direct vLLM, Module 10 needs `MODEL_NAME=vllm/ibm-granite/granite-3.3-8b-instruct` for OGX. The doc should make this transformation explicit, and the smoke test should use the prefixed form.

## Items the playbook recipe got right and the corrected doc carries

These were already in the corrected draft pre-test and held up:
- Operator manifest URL (`v0.9.0`, `ogx-ai/ogx-k8s-operator/release/operator.yaml`)
- Operator namespace (`llama-stack-k8s-operator-system`)
- Operator deployment (`llama-stack-k8s-operator-controller-manager`)
- CRD (`llamastackdistributions.llamastack.io`)
- CR `apiVersion: llamastack.io/v1alpha1`, `kind: LlamaStackDistribution`
- `distribution.image: docker.io/llamastack/distribution-starter:0.7.1`
- `network.allowedFrom.namespaces: ["*"]` (default-deny gotcha avoided)
- `storage.size: "20Gi"`, `mountPath: "/home/lls/.lls"`

## Follow-up tests

### Test A: `distribution.name: starter` instead of pinned image — PASSED

Patched `spec.server.distribution` from `image: docker.io/llamastack/distribution-starter:0.7.1` to `name: starter`. The operator accepted the change, resolved it to `docker.io/llamastack/distribution-starter:0.7.1` (identical image, no rollout triggered), `status.distributionConfig.activeDistribution` flipped to `starter`, and `/v1/models` continued to return `vllm/RedHatAI/gpt-oss-20b`.

**The playbook's "must use image, not name" guidance is stale on v0.9.0.** The doc and manifest were both switched to `name: starter` — more durable, no image-version tracking required.

### Operator reconcile quirk caught during Test B cleanup

When patching `spec.server.distribution.name` from `remote-vllm` (broken — ImagePullBackOff) back to `starter`, the LSD's `.spec` updated correctly but the downstream `Deployment` was **not** re-reconciled — its container image stayed pinned to the bad `distribution-remote-vllm:0.7.1`. Operator log showed `"LlamaStackDistribution CR spec changed"` but no follow-up Deployment update.

Manually deleting the Deployment didn't help — the operator didn't recreate it. A no-op annotation on the LSD (`oc annotate llamastackdistribution ogx reconcile-tap=$(date +%s) --overwrite`) finally triggered a fresh reconcile and the Deployment was recreated with the correct image.

(File against `ogx-ai/ogx-k8s-operator` — the controller should reconcile on every `.spec` change, not only on certain transitions, and should recreate a deleted child Deployment on the next reconcile loop without needing an annotation tap.)

### Test B: `remote-vllm` distribution to skip userConfig — FAILED

Patched to `distribution.name: remote-vllm` and removed `userConfig`. ImagePullBackOff with `manifest unknown` for `docker.io/llamastack/distribution-remote-vllm:0.7.1`.

The operator's `status.distributionConfig.availableDistributions` advertises:

```
"remote-vllm": "docker.io/llamastack/distribution-remote-vllm:0.7.1"
```

But that tag was never published. Docker Hub's tag list for the repo tops out at `0.2.12` (last published — predates the Responses API). `:latest` exists but is also `0.2.x`-vintage.

**Conclusion:** the `availableDistributions` field misrepresents reality; many of the listed distributions are unbuilt or abandoned. Stick with `starter` + userConfig ConfigMap. There is no shortcut around the ConfigMap on v0.9.0.

(File this against `ogx-ai/ogx-k8s-operator` — the operator should validate that an advertised distribution image is actually pullable, or at least populate `availableDistributions` only from images it has verified.)

## Final smoke-test result (after all corrections applied)

```bash
$ curl -ks https://ogx-ogx.apps.<cluster>/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"vllm/RedHatAI/gpt-oss-20b","messages":[{"role":"user","content":"In one short sentence, say hello."}],"max_tokens":300}'

# HTTP 200 in 1.45s
# content: "Hello!"
# reasoning_content present (gpt-oss reasoning trace passes through OGX)
# finish_reason: "stop"
# usage.cached_tokens: 32 (prefix-cache hit)
```

OGX → vLLM → gpt-oss-20b path verified end-to-end.

## Working artifacts left on the cluster

For continuation testing (e.g., shields, observability, Module 10 agent):

- `LlamaStackDistribution ogx/ogx`
- `ConfigMap ogx/ogx-config` (Wave 1 minimal — model registration only)
- `Route ogx/ogx` → `https://ogx-ogx.apps.cluster-hpdl7.hpdl7.sandbox2435.opentlc.com` (300s timeout)
- `InferenceService gpt-oss-model/gpt-oss` (vLLM serving `RedHatAI/gpt-oss-20b`, MXFP4 on L40S)
