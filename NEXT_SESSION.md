# Next Session

**Last refreshed:** 2026-05-06 (post Path B Llama Guard validation)

## Where we are

Tutorial content is complete: 12 modules (0–11) + 5 setup guides + 5 reference pages. Reference model is `RedHatAI/gpt-oss-20b`; both shields (`code-scanner` Path A and `llama-guard` Path B) are verified end-to-end against the validation cluster. Plan from here is **multi-cluster validation before declaring tutorial-complete** — one cluster's "works for me" is not enough.

All open work is tracked as GitHub issues on `fips-agents/examples`. Work from the issues; if it's not in an issue, it's not in scope.

## Open issues, in priority order

### 1. [#28 — Automated tutorial walkthrough (Modules 0–11)](https://github.com/fips-agents/examples/issues/28)

Claude runs the entire tutorial top-to-bottom against a target cluster, files/fixes any drift between docs and reality, hands off to the human walkthrough only after that pass is clean. Pattern from prior iterations: this is the slow path's blocker — humans should not be exposed to doc bugs the automated pass would have caught.

This is the **first** of several cluster validations, not the only one. Each new cluster shape (different RHOAI version, different KServe service config, different GPU mix) is a separate run.

### 2. [#30 — File upstream issues against `meta-llama/llama-stack` and `ogx-ai/ogx-k8s-operator`](https://github.com/fips-agents/examples/issues/30)

Five drafts ready in the issue body and a follow-up comment:

- D1: operator advertises an unbuilt `distribution-remote-vllm:0.7.1`
- D2: operator skips child-Deployment reconciliation on `.spec` change
- D3: `setup_telemetry()` initializes `MeterProvider` but not `TracerProvider`
- D4: `inline::llama-guard` provider ignores `shield.params.model`
- D5: `remote::vllm` provider's `max_tokens` defaults to model's full `max_model_len`

Filing happens in its own session — research each upstream repo's CONTRIBUTING/issue-template first; do not file before reading the rules of the room.

### 3. [#29 — Human walkthrough](https://github.com/fips-agents/examples/issues/29) (blocked by #28)

Clean-room read-through for flow and clarity. Only worth scheduling once #28's automated pass is clean.

## Cluster state — `cluster-hpdl7-sandbox2435` (contexts: `kagenti-memory-hub`, `gpt-oss-model`, `ogx`)

| Resource | Namespace | Notes |
|---|---|---|
| `InferenceService gpt-oss` | `gpt-oss-model` | `RedHatAI/gpt-oss-20b` on L40S #1 (RHAIIS:3) |
| `InferenceService llama-guard` | `llama-guard-model` | `RedHatAI/Llama-Guard-4-12B-quantized.w8a8` on L40S #2 (`vllm/vllm-openai:v0.20.1`) |
| `LlamaStackDistribution ogx` | `ogx` | OGX running both shields registered (Wave 2 Path B) |
| `MachineSet l40s-us-east-2a` | `openshift-machine-api` | **2 replicas** (g6e.4xlarge × 2) |
| `MachineSet gpu-us-east-2a` | `openshift-machine-api` | 0 replicas (A10G unfit for LG4) |

**Cost note:** the second L40S costs ~$3.36/hr (~$560/week) idle. If no near-term Path B work, scale `l40s-us-east-2a` back to 1 between sessions; the OGX Wave 2 ConfigMap will start returning errors on `llama-guard` invocations until LG is re-served. (Path A `code-scanner` is unaffected — it has no GPU dependency.)

## Working artifacts to reuse

- `retrospectives/2026-05-06_llama-guard-deploy/manifests/` — verified Path B manifests (LG vLLM ServingRuntime + Wave 2 ConfigMap)
- `retrospectives/2026-05-05_install-ogx-test/manifests/gpt-oss-vllm.yaml` — gpt-oss-20b ServingRuntime
- `retrospectives/<dated>/findings.md` and `RETRO.md` — what surprised us last time, what process worked

## How to refresh this file

When this document goes stale, **delete and rewrite** rather than editing in place. Editing produces hybrids that mislead — the old `NEXT_SESSION.md` carried "all 8 modules" past the addition of Modules 10–11 and "reference model is granite" past the gpt-oss-20b switch, and both went unnoticed for sessions. A clean rewrite catches that.
