# Next session

Resume from the state captured in [`findings.md`](findings.md). The kagenti-memory-hub cluster is left running with vLLM serving `RedHatAI/gpt-oss-20b`, OGX with the Wave 2 ConfigMap (code-scanner shield) and the `opentelemetry-instrument` wrapper, and Jaeger receiving traces.

## 1. Add a second GPU + finish Path B (Llama Guard)

Path B was rewritten in [`docs/guides/configure-shields.md`](../../docs/guides/configure-shields.md) but never exercised — the cluster's single L40S is allocated to the gpt-oss-20b backend. To validate:

1. **Provision a second GPU node** (cluster-side; outside this repo's scope but a precondition for the test). The Llama Guard 3 8B model fits comfortably in a 24 GB GPU at fp16.
2. **Create a HF token secret in `llama-guard-model`** — Llama Guard 3 is gated:
    ```bash
    oc create secret generic hf-token --from-literal=HF_TOKEN=hf_xxx -n llama-guard-model
    ```
3. **Apply the manifests** under `manifests/llama-guard-vllm.yaml` (to be authored — mirror `manifests/gpt-oss-vllm.yaml` with the args from the doc's Path B).
4. **Replace `manifests/ogx-config-wave2.yaml` with the dual-shield ConfigMap** from the doc (registers `code-scanner` *and* `llama-guard`, plus the `vllm-guard` inference provider and the Llama Guard model registration). Apply, restart the OGX deployment, verify `/v1/shields` returns both entries.
5. **Run the smoke test against `llama-guard`** specifically — `POST /v1/safety/run-shield` with content the model should classify as a violation (e.g. detailed instructions for synthesizing a prohibited substance).

Notes:
- The doc currently says `params.model: meta-llama/Llama-Guard-3-8B` (bare id, not the `vllm-guard/...` prefix). Verify on the cluster — if the prefix is required, fix the doc.
- Resource pressure: with two GPUs in use, the cluster's CPU/memory headroom shrinks — keep an eye on the OGX pod's resource limits during the test.

## 2. File upstream issues

Three upstream-worthy bugs landed during this session (a fourth was our doc bug, already fixed). Open one issue each:

### a. `ogx-ai/ogx-k8s-operator` — `availableDistributions` advertises unpullable images

The CR's `.status.distributionConfig.availableDistributions` lists `remote-vllm: docker.io/llamastack/distribution-remote-vllm:0.7.1`, but that tag was never published. Docker Hub's tag list for the repo tops out at `0.2.12`. Setting `spec.server.distribution.name: remote-vllm` results in `ImagePullBackOff` with `manifest unknown`.

The operator should validate that an advertised distribution image is actually pullable (or only populate `availableDistributions` from images it has verified). Repro is in `findings.md` "Test B".

### b. `ogx-ai/ogx-k8s-operator` — controller doesn't reconcile child Deployment on every CR spec change

Symptom: after patching `spec.server.distribution` from a broken value (`remote-vllm` w/ unpullable image) back to `starter`, the LSD `.spec` updated but the downstream `Deployment` kept the failing image. Operator log showed `"LlamaStackDistribution CR spec changed"` but no follow-up Deployment update. Manually deleting the Deployment didn't help — operator didn't recreate it. A no-op annotation on the LSD finally triggered fresh reconcile and the Deployment was recreated correctly.

The controller should reconcile on every `.spec` change and recreate a deleted child Deployment on the next reconcile loop without needing an annotation tap.

### c. `meta-llama/llama-stack` (preferred) or `ogx-ai/ogx-k8s-operator` — `setup_telemetry()` doesn't initialize `TracerProvider`

`llama_stack/telemetry/__init__.py` calls `metrics.set_meter_provider(provider)` but never sets up a `TracerProvider`. Routers do `from opentelemetry import trace` and create spans (e.g. `core/routers/safety.py` line 7), but with no `TracerProvider` configured, spans go to the no-op default tracer and are discarded — meaning `OTEL_EXPORTER_OTLP_ENDPOINT` alone exports metrics-only.

For trace export to work today, the OGX container entrypoint must be wrapped with `opentelemetry-instrument` (see [`docs/guides/observability-backends.md`](../../docs/guides/observability-backends.md) §4 for the workaround). Once `setup_telemetry()` initializes a `TracerProvider` from the same env vars, the wrapper becomes unnecessary.

If filing against `ogx-ai/ogx-k8s-operator` instead: the operator should ship the wrapper as the default container entrypoint.

## 3. Develop the e2e test scenario

Goal: a single, repeatable scenario that exercises the full Module 10 platform-mode path and produces concrete artifacts (traces, shield decisions, response bodies) that can be screenshot'd into the docs.

Suggested flow — to be turned into a script under `retrospectives/2026-05-05_install-ogx-test/test/e2e.sh`:

| Step | Call | Expected outcome | Trace expected |
|------|------|------------------|----------------|
| 1 | `GET $OGX_ENDPOINT/models` | Returns `vllm/RedHatAI/gpt-oss-20b` (and Llama Guard model after Path B) | `GET /v1/models` |
| 2 | `GET $OGX_ENDPOINT/shields` | Returns `code-scanner` (and `llama-guard` after Path B) | `GET /v1/shields` |
| 3 | `POST $OGX_ENDPOINT/safety/run-shield` `{shield:"code-scanner", messages:[eval(input())]}` | `violation_type: "eval-with-expression,insecure-eval-use"` | `POST /v1/safety/run-shield` + shield internal span |
| 4 | `POST $OGX_ENDPOINT/safety/run-shield` `{shield:"code-scanner", messages:[hello world]}` | `{"violation": null}` | same |
| 5 | `POST $OGX_ENDPOINT/safety/run-shield` `{shield:"llama-guard", messages:[<unsafe content>]}` | violation w/ Llama Guard category | same |
| 6 | `POST $OGX_ENDPOINT/chat/completions` plain prompt | `content: "..."` + `reasoning_content` | `POST /v1/chat/completions` + `chat <model>` + `connect` to vLLM |
| 7 | `POST $OGX_ENDPOINT/chat/completions` with a `tools` array (a calculus tool from `calculus-helper`) | response includes `tool_calls` | trace shows tool-call spans |
| 8 | **(Module 10 path)** `POST $OGX_ENDPOINT/responses` with `guardrails: ["code-scanner"]` and prompt that should be blocked | refusal w/ shield citation | trace shows shield evaluation before/after model call |
| 9 | Same Responses request with benign prompt | normal completion | normal trace |
| 10 | `GET $JAEGER_UI/api/traces?service=ogx&limit=20` | At least 8 distinct traces, one per request | n/a |

Capture artifacts per step into `retrospectives/2026-05-05_install-ogx-test/test/output/` so a future docs pass can reuse them.

Open question for the scenario: is Module 10's agent-template the right driver, or do we want a thinner script first to isolate OGX behavior? My lean is **thinner script first** — gets us a working baseline before debugging agent-template specifics. The agent-template e2e becomes step 11.

## 4. Run the e2e test and capture

Once steps 1 + 2 + 3 are done, run the scenario and:

- **Update the docs with real outputs** where they currently show illustrative JSON (the model registration block in `install-ogx.md`, the violation block in `configure-shields.md`, the operation-name list in `observability-backends.md`).
- **Add screenshots** of the Jaeger UI showing a multi-span trace to `docs/assets/` and reference from the relevant guides.
- **Promote the e2e script** to a real spot in the repo (`tests/e2e/` or similar) so future tutorial-completeness checks have something to run.

## 5. Adjacent work surfaced this session, not yet picked up

- **Module 10 / 11 doc validation against the rewritten guides.** The Module 10 walkthrough was authored against the *old* `install-ogx.md` (with `OGXDistribution` etc.). It needs a read-through against the current set of corrections, especially the `MODEL_NAME=vllm/<bare>` prefix — Module 10's agent code may need adjustment, or the doc may need to call out that platform mode requires the prefixed name.
- **`calculus-agent` end-to-end against gpt-oss-20b.** The reference model switch from granite to gpt-oss is structural for the whole tutorial; we haven't verified the calculus-agent's tool-calling reliability holds on gpt-oss with the args we pinned (`--enable-auto-tool-choice --tool-call-parser openai`). Run the agent-template test suite against this cluster's vLLM in addition to the OGX path.

## Cluster handoff state (kagenti-memory-hub)

End-of-session running components, all healthy:

| Namespace | Workload | Notes |
|-----------|----------|-------|
| `gpt-oss-model` | KServe `InferenceService gpt-oss` (vLLM gpt-oss-20b) | L40S allocated, MXFP4 |
| `ogx` | `LlamaStackDistribution ogx` w/ Wave 2 ConfigMap + opentelemetry-instrument wrapper | 4 OTel env vars set, `code-scanner` shield registered |
| `observability` | `Deployment jaeger` (1.76.0) | OTLP HTTP receiver on port 4318, UI Route exposed |
| `llama-stack-k8s-operator-system` | OGX Operator v0.9.0 | manages the LSD CR |

The 6 kagenti CRDs and 10 workshop namespaces from the pre-session state were cleaned out. The cluster is ready for next-session work without further teardown.
