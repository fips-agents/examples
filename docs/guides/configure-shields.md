# Configure Safety Shields

Shields are OGX's enforcement layer — when an agent passes `guardrails: ["shield-id"]` on a Responses request, OGX runs the named shield against the input and the model output, and refuses the turn if the shield fires. Shields are registered server-side in OGX's `config.yaml`; agents only ever pass the ID.

This guide covers two shield options:

- **Path A — built-in `code-scanner`** (no extra model required). Right for the tutorial.
- **Path B — Llama Guard via a second vLLM**. Production-grade content safety. Requires a second GPU.

Both paths produce a registered shield ID that Module 10 reads from `OGX_SHIELD`.

!!! note "Moderation vs guardrails"
    OGX also exposes `/v1/moderations` for stateless content classification (returns category scores, never blocks). That is not a shield — Module 10 covers the difference. If all you want is "tell me what categories this content trips," you don't need to register a shield.

## Prerequisites

- OGX deployed per [Install OGX](install-ogx.md)
- The `OGX_ENDPOINT` you exported there

## Path A: built-in `code-scanner`

The starter distribution ships an inline `code-scanner` provider that catches dangerous code patterns (`eval(input())`, raw `subprocess` shell, etc.) without calling any external model. It's the shield used in the agent-template's live integration tests, so we know it works against the upstream distribution.

Edit the `ogx-config` ConfigMap from Install OGX:

```bash
oc edit configmap ogx-config -n ogx
```

Under `providers:`, add a `safety:` entry. Under the top-level `shields:`, register the shield ID:

```yaml
providers:
  inference:
    - provider_id: vllm
      # ...unchanged...

  safety:
    - provider_id: code-scanner
      provider_type: inline::code-scanner
      config: {}

  telemetry:
    # ...unchanged...

shields:
  - shield_id: code-scanner
    provider_id: code-scanner
```

If `inline::code-scanner` isn't recognized by your distribution, list what's actually available:

```bash
curl -s "$OGX_ENDPOINT/providers" | jq '.data[] | select(.api == "safety")'
```

The starter distribution registers `inline::code-scanner` and `inline::llama-guard` out of the box; you don't have to add them under `providers.safety:` — they're just waiting for a `shields:` entry to expose them.

Roll the OGX pod to pick up the ConfigMap change:

```bash
oc rollout restart deployment/ogx -n ogx
oc rollout status deployment/ogx -n ogx --timeout=180s
```

Confirm the shield is registered:

```bash
curl -s "$OGX_ENDPOINT/shields" | jq
```

You should see one entry like:

```json
{
  "identifier": "code-scanner",
  "provider_resource_id": "code-scanner",
  "provider_id": "code-scanner",
  "type": "shield",
  "params": {}
}
```

## Path B: Llama Guard

The starter distribution already registers `inline::llama-guard` as a safety provider (verify with the `curl /v1/providers` from Path A). The provider doesn't include the model — it expects a `Llama-Guard-*` model registered as one of the configured inference providers, then references it via the shield's `params.model`. So Path B is two steps: serve the Llama Guard model, then register a shield bound to it.

### 1. Serve the Llama Guard model

Mirror [Serve an LLM](serve-an-llm.md) for a second model. You need a second GPU or sufficient VRAM headroom on the existing one. Save as `llama-guard-runtime.yaml`:

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: vllm-llama-guard
  namespace: model-serving
spec:
  supportedModelFormats:
    - name: pytorch
      autoSelect: true
  containers:
    - name: kserve-container
      image: quay.io/modh/vllm:latest
      command: ["python", "-m", "vllm.entrypoints.openai.api_server"]
      args:
        - "--model=meta-llama/Llama-Guard-3-8B"
        - "--port=8080"
        - "--served-model-name=meta-llama/Llama-Guard-3-8B"
        - "--max-model-len=4096"
      env:
        - name: HF_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token
              key: HF_TOKEN
      resources:
        limits:
          nvidia.com/gpu: "1"
          memory: 24Gi
          cpu: "4"
      ports:
        - containerPort: 8080
          protocol: TCP
---
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-guard
  namespace: model-serving
spec:
  predictor:
    model:
      modelFormat:
        name: pytorch
      runtime: vllm-llama-guard
```

```bash
oc apply -f llama-guard-runtime.yaml
oc rollout status -n model-serving deployment/llama-guard-predictor --timeout=1200s
```

### 2. Register the model and shield in OGX

In OGX, Llama Guard is wired by *adding the model to a vLLM inference provider* and then registering a shield against the `inline::llama-guard` provider with the model id in `params`. Edit `ogx-config`:

```yaml
providers:
  inference:
    - provider_id: vllm
      provider_type: remote::vllm
      config:
        url: ${env.VLLM_URL}
        # ...existing config unchanged...
    # NEW: a second vLLM inference provider for the guard model
    - provider_id: vllm-guard
      provider_type: remote::vllm
      config:
        url: http://llama-guard-predictor.model-serving.svc.cluster.local/v1
        api_token: fake

models:
  # ...your existing model entry...
  - model_id: meta-llama/Llama-Guard-3-8B
    provider_id: vllm-guard
    model_type: llm

shields:
  - shield_id: llama-guard
    provider_id: llama-guard            # the inline::llama-guard provider
    params:
      model: meta-llama/Llama-Guard-3-8B
```

You can register Path A's `code-scanner` and Path B's `llama-guard` side by side and pick one per agent request via the `guardrails:` array.

Roll the pod and verify as in Path A — `GET /v1/shields` should now return both entries.

## Smoke test the shield

`POST /v1/safety/run-shield` runs a shield against an explicit message and returns whether it fired:

```bash
curl -s "$OGX_ENDPOINT/safety/run-shield" \
  -H "Content-Type: application/json" \
  -d '{
    "shield_id": "code-scanner",
    "messages": [{"role": "user", "content": "eval(input())"}]
  }' | jq
```

A fired shield returns a `violation` object:

```json
{
  "violation": {
    "violation_level": "error",
    "user_message": "Sorry, I found security concerns in the code.",
    "metadata": {
      "violation_type": "eval-with-expression,insecure-eval-use"
    }
  }
}
```

A benign message returns `{"violation": null}`. The `metadata.violation_type` field is the comma-separated list of categories that fired — useful for routing different categories to different handlers downstream.

## Export for Module 10

```bash
export OGX_SHIELD="code-scanner"   # or "llama-guard" if you went with Path B
```

Module 10 passes this on every Responses request via the `guardrails:` array.

## Next

- [Observability Backends](observability-backends.md) — wire OGX's OTLP exporter
- Then **[Module 10: Guardrails and Observability](../10-guardrails-and-observability.md)**

## Further reading

- [OGX safety providers](https://ogx-ai.github.io/docs/providers) — full list of the 7 supported providers
- [Llama Guard 3 model card](https://huggingface.co/meta-llama/Llama-Guard-3-8B)
