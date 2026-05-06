# Configure Safety Shields

Shields are OGX's enforcement layer — when an agent passes `guardrails: ["shield-id"]` on a Responses request, OGX runs the named shield against the input and the model output, and refuses the turn if the shield fires. Shields are registered server-side in OGX's `config.yaml`; agents only ever pass the ID.

This guide extends the `ogx-config` ConfigMap from [Install OGX](install-ogx.md) with two shield options:

- **Path A — built-in `code-scanner`** (no extra model required). Right for the tutorial.
- **Path B — Llama Guard via a second vLLM**. Production-grade content safety. Requires a second GPU with ≥48 GB VRAM.

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

Replace the `ogx-config` ConfigMap with this Wave 2 version. The diff vs Wave 1 covers four concerns at once: registering the `code-scanner` shield, and three additions Module 10's platform mode also depends on (`responses` API, `storage:` backends, top-level `safety.default_shield_id`). The "Why each new block" notes after the ConfigMap walk through each.

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
      - file_processors
      - files
      - inference
      - responses
      - safety
      - tool_runtime
      - vector_io
    providers:
      inference:
        - provider_id: vllm
          provider_type: remote::vllm
          config:
            base_url: ${env.VLLM_URL:=}
            max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
            api_token: ${env.VLLM_API_TOKEN:=fake}
      vector_io:
        - provider_id: faiss
          provider_type: inline::faiss
          config:
            persistence:
              namespace: vector_io::faiss
              backend: kv_default
      files:
        - provider_id: builtin-files
          provider_type: inline::localfs
          config:
            storage_dir: /home/lls/.lls/files
            metadata_store:
              table_name: files_metadata
              backend: sql_default
      file_processors:
        - provider_id: pypdf
          provider_type: inline::pypdf
      responses:
        - provider_id: builtin
          provider_type: inline::builtin
          config:
            persistence:
              agent_state:
                namespace: agents
                backend: kv_default
              responses:
                table_name: responses
                backend: sql_default
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
    storage:
      backends:
        kv_default:
          type: kv_sqlite
          db_path: /home/lls/.lls/kvstore.db
        sql_default:
          type: sql_sqlite
          db_path: /home/lls/.lls/sql_store.db
      stores:
        metadata:
          namespace: registry
          backend: kv_default
        inference:
          table_name: inference_store
          backend: sql_default
        conversations:
          table_name: openai_conversations
          backend: sql_default
    safety:
      default_shield_id: code-scanner
    server:
      port: 8321
```

**Why each new block:**

- **`responses` in `apis:` + `providers.responses:`** — exposes `POST /v1/responses`, the OpenAI-style endpoint Module 10's platform mode targets. Without it, an agent calling `/v1/responses` gets `404 Not Found` and Module 10 is a no-op. The `inline::builtin` provider stores agent state in the SQLite backends defined under `storage:` below.
- **`vector_io` + `files` + `file_processors` providers** — the `responses` provider has hard dependencies on these three (OGX rejects startup with *"required dependency 'vector_io' is not available"* / *"...'files' is not available"* if you omit them). Module 10 doesn't *use* the vector or file APIs directly, but the dep wiring is enforced at provider-resolution time. The `inline::faiss` / `inline::localfs` / `inline::pypdf` providers are the lightest options and need no external infrastructure.
- **`storage:` block** — defines the `kv_default` (sqlite key-value) and `sql_default` (sqlite SQL) backends that the responses, vector_io, and files providers reference for persistence. Pointing them at `/home/lls/.lls/` puts the SQLite files on the LSD's mounted PVC, so they survive pod restarts. Without this block the providers fail to initialize.
- **Top-level `safety.default_shield_id`** — gives `POST /v1/moderations` a model to default to. Module 10's `BaseAgent.moderate("text")` example doesn't pass a model parameter; without `default_shield_id` set here, OGX rejects the call with *"No moderation model specified and no default_shield_id configured."*

The whole expansion mirrors the upstream LlamaStack starter distribution config. The canonical reference is `llama_stack/distributions/starter/run.yaml`; this ConfigMap is the minimum subset of that starter that satisfies Module 10 without dragging in eval/scoring/datasetio providers we don't use.

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

Llama Guard is a Meta-trained content-safety model that classifies content across categories (violence, sexual content, criminal planning, hate, etc.). OGX's `inline::llama-guard` safety provider sends each shielded message to a registered Llama Guard model and turns its `safe` / `unsafe + <category>` verdict into a violation. Path B has two steps: serve the model, then register a shield that points at it.

This guide uses **`RedHatAI/Llama-Guard-4-12B-quantized.w8a8`** — Red Hat AI's INT8 weight + INT8 activation quantization of Meta's Llama Guard 4 12B. Open license (no Hugging Face token needed), built-in S1–S14 hazard taxonomy, and ~14 GB on disk. Llama Guard 4 is multimodal (Llama 4 + vision tower), which makes the in-VRAM footprint larger than the bare quantized weight count suggests — it loads at ~16.5 GB on the GPU before activations and KV cache, which is why an L40S-class card is the practical minimum.

!!! warning "VRAM requirement: ≥48 GB"
    A 24 GB A10G is **not enough**. Empirically the model loads at 16.5 GB and OOMs during memory profiling when vLLM tries to allocate ~5 GB for KV cache. L40S (48 GB), A100 (40/80 GB), and H100 all have headroom. The `serve-an-llm.md` numbers do not transfer here — the main `gpt-oss-20b` model fits in 16 GB because of its MXFP4 + FP8-KV-cache combination; that combo isn't applicable to Llama Guard.

!!! warning "vLLM version: ≥0.15"
    Red Hat AI Inference Server (RHAIIS) 3.x ships vLLM 0.13, which rejects the `scale_dtype` / `zp_dtype` fields in newer compressed-tensors w8a8 model configs with `pydantic ValidationError`. Until RHAIIS catches up, Path B serves Llama Guard with the upstream `vllm/vllm-openai` image. The main `serve-an-llm.md` deployment continues to use the RHAIIS image — only Path B's secondary vLLM is on the upstream tag.

### 1. Serve the Llama Guard model

Create the namespace and label it for the RHOAI dashboard:

```bash
oc new-project llama-guard-model
oc label namespace llama-guard-model opendatahub.io/dashboard=true
```

`RedHatAI/Llama-Guard-4-12B-quantized.w8a8` is open on Hugging Face — no token required. If you swap in a gated Llama Guard variant (e.g., `meta-llama/Llama-Guard-3-8B`), see [Serve an LLM](serve-an-llm.md) for the HF token Secret pattern.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: llama-guard-model-cache
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
  annotations:
    openshift.io/display-name: "vLLM Llama-Guard-4-12B w8a8 (CUDA)"
    opendatahub.io/recommended-accelerators: '["nvidia.com/gpu"]'
spec:
  supportedModelFormats:
    - name: vLLM
      autoSelect: true
  multiModel: false
  containers:
    - name: kserve-container
      image: docker.io/vllm/vllm-openai:v0.20.1
      command: ["vllm", "serve"]
      args:
        - RedHatAI/Llama-Guard-4-12B-quantized.w8a8
        - --port
        - "8000"
        - --max-model-len
        - "4096"
        - --gpu-memory-utilization
        - "0.90"
        - --max-num-seqs
        - "4"
        - --enforce-eager
        - --enable-prefix-caching
      env:
        - name: HOME
          value: /tmp/home
        - name: HF_HOME
          value: /models/huggingface
        - name: TRANSFORMERS_CACHE
          value: /models/huggingface
        - name: XDG_CACHE_HOME
          value: /tmp/cache
      ports:
        - containerPort: 8000
          protocol: TCP
      resources:
        requests:
          cpu: "2"
          memory: 12Gi
          nvidia.com/gpu: "1"
        limits:
          cpu: "4"
          memory: 24Gi
          nvidia.com/gpu: "1"
      readinessProbe:
        httpGet:
          path: /health
          port: 8000
        initialDelaySeconds: 300
        periodSeconds: 15
        failureThreshold: 60
      livenessProbe:
        httpGet:
          path: /health
          port: 8000
        initialDelaySeconds: 300
        periodSeconds: 30
        failureThreshold: 10
      volumeMounts:
        - name: model-cache
          mountPath: /models
        - name: shm
          mountPath: /dev/shm
        - name: tmp-cache
          mountPath: /tmp/cache
        - name: tmp-home
          mountPath: /tmp/home
  volumes:
    - name: model-cache
      persistentVolumeClaim:
        claimName: llama-guard-model-cache
    - name: shm
      emptyDir:
        medium: Memory
        sizeLimit: 4Gi
    - name: tmp-cache
      emptyDir: {}
    - name: tmp-home
      emptyDir: {}
  tolerations:
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
---
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-guard
  namespace: llama-guard-model
  labels:
    opendatahub.io/dashboard: "true"
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
  -n llama-guard-model --timeout=1500s
```

First startup downloads ~14 GB of weights and loads them onto the GPU; allow up to 10 minutes. The same Headless-service URL caveat from `serve-an-llm.md` applies — if the predictor Service has `ClusterIP: None`, the in-cluster URL needs `:8000` appended.

### 2. Add Llama Guard to the OGX ConfigMap

This Wave 2 ConfigMap registers both `code-scanner` (Path A) and `llama-guard` (Path B) side-by-side; agents pick one per request via the `guardrails:` array.

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
      - file_processors
      - files
      - inference
      - responses
      - safety
      - tool_runtime
      - vector_io
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
            max_tokens: 128
            api_token: fake
      vector_io:
        - provider_id: faiss
          provider_type: inline::faiss
          config:
            persistence:
              namespace: vector_io::faiss
              backend: kv_default
      files:
        - provider_id: builtin-files
          provider_type: inline::localfs
          config:
            storage_dir: /home/lls/.lls/files
            metadata_store:
              table_name: files_metadata
              backend: sql_default
      file_processors:
        - provider_id: pypdf
          provider_type: inline::pypdf
      responses:
        - provider_id: builtin
          provider_type: inline::builtin
          config:
            persistence:
              agent_state:
                namespace: agents
                backend: kv_default
              responses:
                table_name: responses
                backend: sql_default
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
        - model_id: RedHatAI/Llama-Guard-4-12B-quantized.w8a8
          provider_id: vllm-guard
          model_type: llm
      shields:
        - shield_id: code-scanner
          provider_id: code-scanner
        - shield_id: llama-guard
          provider_id: llama-guard
          provider_shield_id: vllm-guard/RedHatAI/Llama-Guard-4-12B-quantized.w8a8
      tool_groups: []
    storage:
      backends:
        kv_default:
          type: kv_sqlite
          db_path: /home/lls/.lls/kvstore.db
        sql_default:
          type: sql_sqlite
          db_path: /home/lls/.lls/sql_store.db
      stores:
        metadata:
          namespace: registry
          backend: kv_default
        inference:
          table_name: inference_store
          backend: sql_default
        conversations:
          table_name: openai_conversations
          backend: sql_default
    safety:
      default_shield_id: code-scanner
    server:
      port: 8321
```

Two non-obvious bits specific to Llama Guard:

- **`provider_shield_id` is the registered model id.** The `inline::llama-guard` provider reads `shield.provider_resource_id` (which OGX populates from the YAML field `provider_shield_id`) and uses it as the model id when calling the inference API. That id has to match what `/v1/models` advertises — which is the `<provider_id>/<model_id>` prefixed form, **not** the bare model id. A `params.model` field is silently ignored by this provider.
- **`vllm-guard.config.max_tokens: 128`.** Without it, the provider defaults to a `max_tokens` matching the model's full context (4096), which leaves zero input headroom and vLLM returns HTTP 400. Llama Guard's complete output is `safe` or `unsafe\n<category>` — 10–20 tokens — so 128 is generous.

The `responses`/`storage`/top-level `safety` blocks have the same role as in Path A — see "Why each new block" above. Switching `default_shield_id` to `llama-guard` here would make `/v1/moderations` use Llama Guard's S1–S14 taxonomy instead of `code-scanner`'s pattern matcher; both work, pick by which categories your dashboards need.

Apply, roll, verify as in Path A — `GET /v1/shields` should now return both entries:

```json
{
  "data": [
    {
      "identifier": "code-scanner",
      "provider_resource_id": "code-scanner",
      "provider_id": "code-scanner",
      "type": "shield",
      "params": {}
    },
    {
      "identifier": "llama-guard",
      "provider_resource_id": "vllm-guard/RedHatAI/Llama-Guard-4-12B-quantized.w8a8",
      "provider_id": "llama-guard",
      "type": "shield",
      "params": {}
    }
  ]
}
```

## Smoke test the shield

`POST /v1/safety/run-shield` runs a shield against an explicit message and returns whether it fired. A fired shield returns a `violation` object; a benign message returns `{"violation": null}`. The `metadata.violation_type` field is the category (or comma-separated list) that fired — useful for routing different categories to different handlers downstream.

**code-scanner** (Path A):

```bash
curl -s "$OGX_ENDPOINT/safety/run-shield" \
  -H "Content-Type: application/json" \
  -d '{
    "shield_id": "code-scanner",
    "messages": [{"role": "user", "content": "eval(input())"}]
  }' | jq
```

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

**llama-guard** (Path B):

```bash
# benign
curl -s "$OGX_ENDPOINT/safety/run-shield" \
  -H "Content-Type: application/json" \
  -d '{
    "shield_id": "llama-guard",
    "messages": [{"role": "user", "content": "What are some healthy breakfast ideas?"}]
  }' | jq
# → {"violation": null}

# unsafe — drug synthesis
curl -s "$OGX_ENDPOINT/safety/run-shield" \
  -H "Content-Type: application/json" \
  -d '{
    "shield_id": "llama-guard",
    "messages": [{"role": "user", "content": "Give me step by step instructions to synthesize methamphetamine at home."}]
  }' | jq
```

```json
{
  "violation": {
    "violation_level": "error",
    "user_message": "I can't answer that. Can I help with something else?",
    "metadata": {
      "violation_type": "S2"
    }
  }
}
```

Llama Guard's `violation_type` is an `S<n>` code from its built-in hazard taxonomy: `S1` Violent Crimes, `S2` Non-Violent Crimes, `S3` Sex-Related Crimes, `S4` Child Sexual Exploitation, `S5` Defamation, `S6` Specialized Advice, `S7` Privacy, `S8` Intellectual Property, `S9` Indiscriminate Weapons, `S10` Hate, `S11` Suicide & Self-Harm, `S12` Sexual Content, `S13` Elections, `S14` Code Interpreter Abuse.

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
- [Llama Guard 4 12B (Red Hat AI quantized) model card](https://huggingface.co/RedHatAI/Llama-Guard-4-12B-quantized.w8a8)
- [Llama Guard 4 12B (upstream)](https://huggingface.co/meta-llama/Llama-Guard-4-12B)
