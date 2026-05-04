# Serve an LLM

The agent in this tutorial talks to an OpenAI-compatible LLM endpoint. The
reference model is **`ibm-granite/granite-3.3-8b-instruct`** served via
**vLLM**. Granite 3.3 8B is small enough to fit on a single 24 GB GPU at
fp16, capable enough to drive multi-turn tool calls reliably, and works
well in FIPS mode — useful since this tutorial targets the `fips-agents`
toolkit.

This guide covers two paths:

- **Path A** — deploy vLLM on your OpenShift cluster (recommended).
- **Path B** — point the tutorial at an external OpenAI-compatible endpoint.

Both paths produce the same two values that the rest of the tutorial reads:

| Variable | Example |
|----------|---------|
| `MODEL_ENDPOINT` | `https://granite-predictor.calculus-mcp.svc.cluster.local/v1` or `https://api.example.com/v1` |
| `MODEL_NAME` | `ibm-granite/granite-3.3-8b-instruct` |

## Path A: Serve on-cluster with vLLM

### Prerequisites

- [OpenShift AI installed](install-openshift-ai.md) with KServe managed
- One GPU node (~24 GB VRAM minimum)
- A namespace to host the model (the tutorial later uses `calculus-mcp`,
  but the model can live anywhere reachable from the agent)

### 1. Create the namespace and a model storage location

vLLM can pull weights directly from Hugging Face at startup. For an
air-gapped cluster, mirror the weights to S3 / OCI storage and use a
KServe storage URI instead — see the [KServe storage docs][kserve-storage].

[kserve-storage]: https://kserve.github.io/website/latest/modelserving/storage/storagecontainers/

```bash
oc new-project model-serving
```

If pulling from Hugging Face, create a secret with your HF token (Granite
models are gated):

```bash
oc create secret generic hf-token \
  --from-literal=HF_TOKEN=hf_xxx \
  -n model-serving
```

### 2. Define a vLLM ServingRuntime

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: vllm-runtime
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
        - "--model=ibm-granite/granite-3.3-8b-instruct"
        - "--port=8080"
        - "--served-model-name=ibm-granite/granite-3.3-8b-instruct"
        - "--max-model-len=8192"
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
        requests:
          nvidia.com/gpu: "1"
          memory: 16Gi
          cpu: "2"
      ports:
        - containerPort: 8080
          protocol: TCP
```

### 3. Define an InferenceService

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: granite
  namespace: model-serving
spec:
  predictor:
    model:
      modelFormat:
        name: pytorch
      runtime: vllm-runtime
```

Apply both:

```bash
oc apply -f vllm-runtime.yaml
oc apply -f inferenceservice.yaml
```

The first startup pulls the model weights and can take 10–20 minutes.
Watch progress:

```bash
oc logs -n model-serving -l serving.kserve.io/inferenceservice=granite -f
```

### 4. Get the endpoint URL

```bash
URL=$(oc get inferenceservice granite -n model-serving \
  -o jsonpath='{.status.url}')
echo "$URL"
# https://granite-model-serving.apps.<cluster-domain>
```

Smoke test:

```bash
curl -s "$URL/v1/models" | jq
curl -s "$URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ibm-granite/granite-3.3-8b-instruct",
    "messages": [{"role": "user", "content": "Hello"}]
  }' | jq
```

### 5. Export the environment variables

```bash
export MODEL_ENDPOINT="${URL}/v1"
export MODEL_NAME="ibm-granite/granite-3.3-8b-instruct"
```

You're ready for Module 1.

## Path B: External OpenAI-compatible endpoint

If you don't have GPU access — Developer Sandbox, CRC, or a cluster with
no GPU node pool — point the tutorial at an external endpoint instead.

Anything that speaks the OpenAI Chat Completions API works:

- A vLLM you run elsewhere (a workstation with a GPU, a separate cluster,
  a cloud VM)
- A corporate inference gateway (e.g., a shared `llm-d` deployment, MaaS,
  or LiteLLM proxy)
- Any OpenAI-compatible third-party API

You need three things:

| Item | Notes |
|------|-------|
| Endpoint URL | Must end at the API root, e.g. `https://api.example.com/v1` |
| Model name | What that endpoint calls the model |
| API key (if required) | Set as `OPENAI_API_KEY`. For unauthenticated endpoints, set it to any non-empty string (e.g. `not-required`) — the OpenAI SDK requires the variable to exist. |

Smoke test before moving on:

```bash
curl -s "$MODEL_ENDPOINT/v1/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq
```

If you get a list of models including the one you'll use, you're ready.

Set the variables:

```bash
export MODEL_ENDPOINT="https://your-endpoint.example.com/v1"
export MODEL_NAME="your-model-id"
export OPENAI_API_KEY="..."
```

The rest of the tutorial works identically — only the LLM lives elsewhere.

## Picking a different model

The tutorial uses Granite 3.3 8B Instruct as its reference, but any
instruction-tuned model with reliable tool-calling support works.
Larger Granite, Llama 3.3 70B Instruct, and Mistral Large all work well
if you have the GPU budget. Smaller models (under ~7B params) may
struggle with tool-call JSON for some calculus tools.

## Next

[Install CLI Tools](install-cli-tools.md).
