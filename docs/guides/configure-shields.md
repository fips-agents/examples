# Configure Safety Shields

Shields are OGX's enforcement layer — when an agent passes `guardrails: ["shield-id"]` on a Responses request, OGX runs the named shield against the input and the model output, and refuses the turn if the shield fires. Shields are registered server-side in OGX's `config.yaml`; agents only ever pass the ID.

This guide extends the `ogx-config` ConfigMap from [Install OGX](install-ogx.md) with two shield options:

- **Path A — built-in `code-scanner`** (no extra model required). Right for the tutorial.
- **Path B — Llama Guard via a second vLLM**. Production-grade content safety. Requires a second GPU.

Both paths produce a registered shield ID that Module 10 reads from `OGX_SHIELD`.

!!! note "Moderation vs guardrails"
    OGX also exposes `/v1/moderations` for stateless content classification (returns category scores, never blocks). That is not a shield — Module 10 covers the difference. If all you want is "tell me what categories this content trips," you don't need to register a shield.

!!! warning "userConfig replaces — it does not merge"
    The `userConfig` ConfigMap *replaces* the starter image's bundled `run.yaml` wholesale. Anything not listed in your ConfigMap is gone, including bundled safety providers. Each path below shows the **complete** ConfigMap to apply, not a delta.

## Prerequisites

- OGX deployed per [Install OGX](install-ogx.md), with the Wave 1 `ogx-config` ConfigMap in place
- The `OGX_ENDPOINT` you exported there

## Path A: built-in `code-scanner`

The starter distribution ships an inline `code-scanner` provider that catches dangerous code patterns (`eval(input())`, raw `subprocess` shell, etc.) without calling any external model. It's the shield used in the agent-template's live integration tests, so we know it works against the upstream distribution.

Replace the `ogx-config` ConfigMap with this Wave 2 version. The diff vs Wave 1 is two additions: `safety` in `apis`, `providers.safety` with the `code-scanner` provider, and one entry under `registered_resources.shields`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ogx-config
  namespace: ogx
data:
  config.yaml: |
    version: 2
    image_name: tutorial
    apis:
      - inference
      - safety
      - tool_runtime
    providers:
      inference:
        - provider_id: vllm
          provider_type: remote::vllm
          config:
            base_url: ${env.VLLM_URL:=}
            max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
            api_token: ${env.VLLM_API_TOKEN:=fake}
      safety:
        - provider_id: code-scanner
          provider_type: inline::code-scanner
          config: {}
    registered_resources:
      models:
        - model_id: ${env.VLLM_INFERENCE_MODEL}
          provider_id: vllm
          model_type: llm
      shields:
        - shield_id: code-scanner
          provider_id: code-scanner
      tool_groups: []
    server:
      port: 8321
```

```bash
oc apply -f ogx-config.yaml
```

Roll the OGX pod to pick up the change:

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

Llama Guard is a Meta-trained content-safety model that classifies content across categories (violence, sexual content, criminal planning, hate, etc.). OGX's `inline::llama-guard` safety provider expects a `Llama-Guard-*` model registered as one of the configured inference providers, then references it via the shield's `params.model`. So Path B is two steps: serve the Llama Guard model, then register a shield bound to it.

!!! warning "Path B requires a second GPU"
    The kagenti-memory-hub cluster the tutorial validates against has a single GPU consumed by the main inference model, so the manifests below were not exercised end-to-end. They mirror the verified `serve-an-llm.md` patterns; treat them as a known-shape recipe and verify on your own cluster.

### 1. Serve the Llama Guard model

Mirror [Serve an LLM](serve-an-llm.md) for a second model in its own namespace. Llama Guard 3 8B is gated on Hugging Face — create a token secret first:

```bash
oc new-project llama-guard-model
oc label namespace llama-guard-model opendatahub.io/dashboard=true
oc create secret generic hf-token \
  --from-literal=HF_TOKEN=hf_xxx -n llama-guard-model
```

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: llama-guard-cache
  namespace: llama-guard-model
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: gp3-csi
  resources:
    requests:
      storage: 50Gi
---
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: vllm-llama-guard-runtime
  namespace: llama-guard-model
  labels:
    opendatahub.io/dashboard: "true"
spec:
  supportedModelFormats:
    - name: vLLM
      autoSelect: true
  multiModel: false
  containers:
    - name: kserve-container
      image: registry.redhat.io/rhaiis/vllm-cuda-rhel9:3
      command: ["vllm", "serve"]
      args:
        - meta-llama/Llama-Guard-3-8B
        - --port
        - "8000"
        - --max-model-len
        - "4096"
      env:
        - name: HF_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token
              key: HF_TOKEN
        - name: HF_HOME
          value: /models/huggingface
      ports:
        - containerPort: 8000
          protocol: TCP
      resources:
        requests:
          cpu: "2"
          memory: 16Gi
          nvidia.com/gpu: "1"
        limits:
          cpu: "4"
          memory: 24Gi
          nvidia.com/gpu: "1"
      volumeMounts:
        - name: model-cache
          mountPath: /models
        - name: shm
          mountPath: /dev/shm
  volumes:
    - name: model-cache
      persistentVolumeClaim:
        claimName: llama-guard-cache
    - name: shm
      emptyDir:
        medium: Memory
        sizeLimit: 4Gi
---
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-guard
  namespace: llama-guard-model
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
    sidecar.istio.io/inject: "false"
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      runtime: vllm-llama-guard-runtime
```

```bash
oc apply -f llama-guard.yaml
oc wait --for=condition=Ready inferenceservice/llama-guard \
  -n llama-guard-model --timeout=900s
```

The same Headless-service URL caveat from `serve-an-llm.md` applies — if the predictor Service has `ClusterIP: None`, your in-cluster URL needs `:8000` appended.

### 2. Add Llama Guard to the OGX ConfigMap

This Wave 2 ConfigMap registers both `code-scanner` (Path A) and `llama-guard` (Path B) side-by-side; you can pick one per agent request via the `guardrails:` array. Adjust the `vllm-guard` `base_url` for your cluster's Headless / non-Headless service config:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ogx-config
  namespace: ogx
data:
  config.yaml: |
    version: 2
    image_name: tutorial
    apis:
      - inference
      - safety
      - tool_runtime
    providers:
      inference:
        - provider_id: vllm
          provider_type: remote::vllm
          config:
            base_url: ${env.VLLM_URL:=}
            max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
            api_token: ${env.VLLM_API_TOKEN:=fake}
        - provider_id: vllm-guard
          provider_type: remote::vllm
          config:
            base_url: http://llama-guard-predictor.llama-guard-model.svc.cluster.local:8000/v1
            api_token: fake
      safety:
        - provider_id: code-scanner
          provider_type: inline::code-scanner
          config: {}
        - provider_id: llama-guard
          provider_type: inline::llama-guard
          config: {}
    registered_resources:
      models:
        - model_id: ${env.VLLM_INFERENCE_MODEL}
          provider_id: vllm
          model_type: llm
        - model_id: meta-llama/Llama-Guard-3-8B
          provider_id: vllm-guard
          model_type: llm
      shields:
        - shield_id: code-scanner
          provider_id: code-scanner
        - shield_id: llama-guard
          provider_id: llama-guard
          params:
            model: meta-llama/Llama-Guard-3-8B
      tool_groups: []
    server:
      port: 8321
```

`shields[].params.model` is the bare `model_id` — not the `<provider_id>/<model_id>` prefixed form returned by `/v1/models`.

Apply, roll, verify as in Path A — `GET /v1/shields` should now return both entries.

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

- [OGX safety providers](https://ogx-ai.github.io/docs/providers) — full list of supported providers
- [Llama Guard 3 model card](https://huggingface.co/meta-llama/Llama-Guard-3-8B)
