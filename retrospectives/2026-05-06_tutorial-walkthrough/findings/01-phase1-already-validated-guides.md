# Phase 1 — re-verify already-validated guides

**Date:** 2026-05-06
**Cluster:** `cluster-hpdl7-sandbox2435` (context `kagenti-memory-hub`)
**Targets:** `serve-an-llm.md`, `install-ogx.md`, `configure-shields.md` (Path A + Path B)
**Outcome:** All three guides verify clean against current cluster state. No drift to file.

## What "verify clean" means here

For each guide I walked the prose top-to-bottom and ran the verification commands the guide itself tells the reader to run, plus spot-checks of the resource specs against the YAML in the doc. A guide is "clean" if the documented commands produce the documented output and the deployed resources match the documented YAML closely enough that a reader following the guide cold would land in the same place.

## serve-an-llm.md

| Doc claim | Cluster state | Match |
|---|---|---|
| `gpt-oss-model` ns has `opendatahub.io/dashboard=true` | label set | ✅ |
| PVC `gpt-oss-model-cache`, 100Gi, `gp3-csi`, RWO | bound | ✅ |
| ServingRuntime `vllm-gpt-oss-runtime` with 14 vLLM args + 5 env vars | matches, plus 2 extra args (`--enable-prompt-tokens-details`, `--enable-server-load-tracking`) and 1 extra env (`HF_HUB_OFFLINE=0`) | ✅ baseline correct; cluster has additive observability flags |
| InferenceService `gpt-oss` with `RawDeployment` annotation, `sidecar.istio.io/inject=false` | annotations set, `Ready=True` | ✅ |
| Headless-service caveat: `clusterIP: None` → `:8000` required | confirmed `None` | ✅ caveat still applies |
| Smoke test: `/v1/models` returns `RedHatAI/gpt-oss-20b`, `/v1/chat/completions` returns `Hello!` with populated `reasoning_content` | both match | ✅ |

The two extra vLLM flags on the live runtime (`--enable-prompt-tokens-details`, `--enable-server-load-tracking`) are post-deploy additions for observability — likely added during the Module 10 / observability-backends layering work. They don't conflict with the guide's prose, which describes a minimum viable runtime. No fix needed.

## install-ogx.md

| Doc claim | Cluster state | Match |
|---|---|---|
| Operator deployment `llama-stack-k8s-operator-controller-manager` in `llama-stack-k8s-operator-system`, image `quay.io/llamastack/llama-stack-k8s-operator:v0.9.0` | match | ✅ |
| CRD `llamastackdistributions.llamastack.io` registered | present | ✅ |
| `ogx` ns exists | exists | ✅ |
| LSD `ogx` Ready, replicas=1, `kind: LlamaStackDistribution`, `apiVersion: llamastack.io/v1alpha1` | `PHASE=Ready`, operator v0.9.0, server v0.7.1 | ✅ |
| `containerSpec.env`: VLLM_URL with `/v1`, VLLM_INFERENCE_MODEL, VLLM_MAX_TOKENS=4096, VLLM_API_TOKEN=fake | exact match (plus 4 OTEL_* env vars from observability-backends layer) | ✅ baseline correct |
| `network.allowedFrom.namespaces: ["*"]` (the warning) | `{"namespaces":["*"]}` | ✅ |
| Service `ogx-service:8321` | exists | ✅ |
| Route `ogx`, edge, port 8321, 300s router timeout | annotation `haproxy.router.openshift.io/timeout=300s` set | ✅ |
| Smoke `/v1/models` returns `vllm/RedHatAI/gpt-oss-20b` with `provider_id: vllm` | exact match (plus the `vllm-guard/...` entry from configure-shields) | ✅ |
| Round-trip `/v1/chat/completions` to `vllm/RedHatAI/gpt-oss-20b` | returns content | ✅ |

The OTEL env vars on the live LSD are added by the `observability-backends.md` step (Module 10 path) and are orthogonal to install-ogx's prose. The cluster's two-provider/two-shield state is the configure-shields-extended state stacked on top, also expected.

## configure-shields.md (Paths A + B)

**Path A (`code-scanner`):**

| Doc claim | Cluster state | Match |
|---|---|---|
| Shield registered with the documented JSON shape | `/v1/shields` returns `code-scanner` entry | ✅ |
| Smoke test: `eval(input())` produces `violation_type: "eval-with-expression,insecure-eval-use"` and `user_message: "Sorry, I found security concerns in the code."` | exact match | ✅ |

**Path B (`llama-guard`):**

| Doc claim | Cluster state | Match |
|---|---|---|
| `llama-guard-model` ns has `opendatahub.io/dashboard=true` | label set | ✅ |
| PVC `llama-guard-model-cache`, 50Gi | bound | ✅ |
| ServingRuntime image `vllm/vllm-openai:v0.20.1` (the doc's "≥0.15" workaround for RHAIIS pydantic issue) | `docker.io/vllm/vllm-openai:v0.20.1` | ✅ |
| InferenceService `llama-guard` Ready | `Ready=True` | ✅ |
| Headless-service caveat applies (`clusterIP: None` → `:8000` required) | `clusterIP: None` confirmed | ✅ |
| ConfigMap `ogx-config` matches the Wave 2 Path B yaml verbatim, including `vllm-guard.config.max_tokens: 128` and `provider_shield_id: vllm-guard/RedHatAI/Llama-Guard-4-12B-quantized.w8a8` | byte-for-byte match | ✅ |
| Both shields visible at `/v1/shields` with the documented JSON | exact match | ✅ |
| Benign smoke test → `{"violation": null}` | exact match | ✅ |
| Unsafe (meth synthesis) → `violation_type: "S2"`, `user_message: "I can't answer that. Can I help with something else?"` | exact match | ✅ |

The two non-obvious bits the guide calls out (`provider_shield_id` must be the prefixed model id; `max_tokens: 128` to leave input headroom under Llama Guard's small context) are both present in the live ConfigMap exactly as documented.

## Bottom line

Phase 1 produces no follow-up issues. The three guides covered here are still accurate against the cluster as it sits right now. Move on to Phase 2 (setup guides not recently validated: `cluster-options`, `install-openshift-ai`, `install-cli-tools`, `registry-setup`, `observability-backends`).

## Time + cost

- ~15 min wall time, no resource changes.
- No scaling needed: the second L40S (`cluster-hpdl7-krtmj-l40s-us-east-2a`) was already at 2 replicas, so Path B's `llama-guard` was reachable without a scale-up. Cluster left untouched.
