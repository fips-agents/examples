# Serve an LLM

The agent in this tutorial talks to an OpenAI-compatible LLM endpoint. The
reference model is **`RedHatAI/gpt-oss-20b`** served via **vLLM**. It's a
20 B-parameter Apache-2.0 reasoning model with native tool-calling support;
Red Hat AI's MXFP4-quantized variant fits in ~16 GB of VRAM and runs on a
single L40S/A100/H100 — a realistic single-GPU target for the tutorial. It
also matches the model the [`workshop-setup-ogx`][playbook] playbook
validates end-to-end against OGX, so Module 10's platform-mode install
slots in without re-tuning.

[playbook]: https://github.com/rdwj/workshop-setup-ogx

This guide covers two paths:

- **Path A** — deploy vLLM on your OpenShift cluster (recommended).
- **Path B** — point the tutorial at an external OpenAI-compatible endpoint.

Both paths produce the same variables that the rest of the tutorial reads:

| Variable | Catalog deploy | Manual deploy |
|----------|---------------|---------------|
| `MODEL_ENDPOINT` | `https://redhataigpt-oss-20b-gpt-oss-model.apps.<cluster>/v1` (local dev) or `https://redhataigpt-oss-20b-predictor.gpt-oss-model.svc.cluster.local:8443/v1` (on-cluster) | `http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local:8000/v1` |
| `MODEL_NAME` | `redhataigpt-oss-20b` | `RedHatAI/gpt-oss-20b` |
| `OPENAI_API_KEY` | Service account token from dashboard | `not-required` |

## Path A: Serve on-cluster with vLLM

There are two ways to deploy the model. The catalog deploy is faster and
recommended for most users. The manual deploy gives full control over the
ServingRuntime and InferenceService configuration.

!!! tip "Multi-cluster safety"
    Every `oc` command in this guide includes `--context="$CTX"` to avoid
    targeting the wrong cluster. Set it once per shell session:

    ```bash
    export CTX=$(oc config current-context)
    ```

=== "Deploy from catalog (recommended)"

    ### Prerequisites

    - [OpenShift AI 3.x installed](install-openshift-ai.md) with model registry enabled
    - One GPU node with ~24 GB VRAM (L40S, A10, A100, or H100 all work)
    - RHOAI dashboard accessible

    ### 1. Create the namespace

    ```bash
    oc new-project gpt-oss-model --context="$CTX"
    oc label namespace gpt-oss-model opendatahub.io/dashboard=true --context="$CTX"
    ```

    ### 2. Deploy from the AI hub

    Open the RHOAI dashboard and navigate to **AI hub > Models**.

    Find **gpt-oss-20b** (from RedHatAI) and click **Deploy**.

    In the deployment form:

    - Set the project to `gpt-oss-model`
    - Select the **NVIDIA GPU** hardware profile (created in the install guide)
    - Accept the remaining defaults

    ### 3. Wait for the model

    Wait for the model to show **Ready** status in the dashboard under
    **Models > Deployed models**.

    ### 4. Get the endpoint URL

    Once ready, click on the deployed model. Under **Inference endpoints**,
    you will find:

    - **Internal URL**: `https://redhataigpt-oss-20b-predictor.gpt-oss-model.svc.cluster.local:8443` (for agents deployed on the cluster)
    - **External URL**: `https://redhataigpt-oss-20b-gpt-oss-model.apps.<cluster-domain>` (for local development)
    - **Token**: a service account token for authentication

    !!! info "Model ID difference"
        The catalog deploy registers the model as `redhataigpt-oss-20b` (no
        slashes). This differs from the Hugging Face ID `RedHatAI/gpt-oss-20b`
        used in manual deploys. Use the catalog name when setting `MODEL_NAME`.

    ### 5. Smoke test

    Using the external URL:

    ```bash
    curl -sk "$MODEL_ENDPOINT/models" \
      -H "Authorization: Bearer $OPENAI_API_KEY" | jq
    ```

    ```bash
    curl -sk "$MODEL_ENDPOINT/chat/completions" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $OPENAI_API_KEY" \
      -d '{
        "model": "redhataigpt-oss-20b",
        "messages": [{"role": "user", "content": "In one short sentence, say hello."}],
        "max_tokens": 300
      }' | jq '.choices[0].message'
    ```

=== "Deploy manually"

    ### Prerequisites

    - [OpenShift AI 3.x installed](install-openshift-ai.md) with KServe managed
    - One GPU node with ~24 GB VRAM (L40S, A10, A100, or H100 all work)
    - A namespace to host the model — this guide uses `gpt-oss-model`

    ### 1. Create the namespace

    ```bash
    oc new-project gpt-oss-model --context="$CTX"
    oc label namespace gpt-oss-model opendatahub.io/dashboard=true --context="$CTX"
    ```

    The label puts the InferenceService under **Models > Deployed models** in
    the RHOAI dashboard.

    `RedHatAI/gpt-oss-20b` is Apache-2.0 and not gated, so no Hugging Face
    token is required. If you swap in a gated model, see the
    [KServe storage docs][kserve-storage] for credential setup.

    [kserve-storage]: https://kserve.github.io/website/latest/modelserving/storage/storagecontainers/

    ### 2. Create a PVC for the weight cache

    The model is ~13 GB on disk. Backing `HF_HOME` with a PVC means the
    weights download once and persist across pod restarts.

    ```yaml
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: gpt-oss-model-cache
      namespace: gpt-oss-model
    spec:
      accessModes:
        - ReadWriteOnce
      storageClassName: gp3-csi
      resources:
        requests:
          storage: 100Gi
    ```

    Substitute your cluster's default block storage class for `gp3-csi` if
    needed (`oc get storageclass`).

    ### 3. Define a ServingRuntime

    The image is Red Hat AI Inference Server (RHAIIS) — RHOAI's productized
    vLLM, recent enough to ship native MXFP4 + Marlin kernels and the
    `openai_gptoss` reasoning parser.

    ```yaml
    apiVersion: serving.kserve.io/v1alpha1
    kind: ServingRuntime
    metadata:
      name: vllm-gpt-oss-runtime
      namespace: gpt-oss-model
      labels:
        opendatahub.io/dashboard: "true"
      annotations:
        openshift.io/display-name: "vLLM gpt-oss-20b (CUDA)"
        opendatahub.io/recommended-accelerators: '["nvidia.com/gpu"]'
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
            - RedHatAI/gpt-oss-20b
            - --port
            - "8000"
            - --dtype
            - bfloat16
            - --max-model-len
            - "131072"
            - --kv-cache-dtype
            - fp8_e4m3
            - --gpu-memory-utilization
            - "0.95"
            - --max-num-seqs
            - "8"
            - --enforce-eager
            - --enable-auto-tool-choice
            - --tool-call-parser
            - openai
            - --enable-prefix-caching
          env:
            - name: HOME
              value: /tmp/home
            - name: HF_HOME
              value: /models/huggingface
            - name: HF_HUB_OFFLINE
              value: "0"
            - name: TRANSFORMERS_CACHE
              value: /models/huggingface
            - name: VLLM_CACHE_DIR
              value: /models/vllm-cache
            - name: XDG_CACHE_HOME
              value: /tmp/cache
          ports:
            - containerPort: 8000
              protocol: TCP
          resources:
            requests:
              cpu: "4"
              memory: 16Gi
              nvidia.com/gpu: "1"
            limits:
              cpu: "8"
              memory: 32Gi
              nvidia.com/gpu: "1"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 300
            periodSeconds: 15
            failureThreshold: 40
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
            claimName: gpt-oss-model-cache
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 8Gi
        - name: tmp-cache
          emptyDir: {}
        - name: tmp-home
          emptyDir: {}
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
    ```

    !!! note "Why these vLLM args"
        - `--dtype bfloat16` + `--kv-cache-dtype fp8_e4m3` — bf16 weights, FP8 KV cache; tuned for L40S-class hardware
        - `--enforce-eager` — disables CUDA graph capture; required for the MXFP4 + Marlin kernel path
        - `--enable-auto-tool-choice --tool-call-parser openai` — exposes gpt-oss's native tool calls in the standard OpenAI `tool_calls` field. Modules 4-9 of this tutorial rely on this.
        - `--max-model-len 131072` — gpt-oss-20b's full 128 k context

    ### 4. Define an InferenceService

    The `RawDeployment` annotation tells KServe to use a plain Deployment
    + Service rather than Knative — required on RHOAI 3.x clusters where
    KServe's `rawDeploymentServiceConfig` is `Headless`.

    ```yaml
    apiVersion: serving.kserve.io/v1beta1
    kind: InferenceService
    metadata:
      name: gpt-oss
      namespace: gpt-oss-model
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
          runtime: vllm-gpt-oss-runtime
    ```

    Apply all three manifests:

    ```bash
    oc apply --context="$CTX" -n gpt-oss-model -f pvc.yaml
    oc apply --context="$CTX" -n gpt-oss-model -f vllm-runtime.yaml
    oc apply --context="$CTX" -n gpt-oss-model -f inferenceservice.yaml
    ```

    !!! tip "Joining an existing cluster?"
        If the model was deployed by someone else, the KServe service name may differ from `gpt-oss-predictor` (e.g. it could be `gpt-oss-20b-predictor` or any other name chosen at deploy time). Run `oc get svc -n <model-namespace> --context="$CTX"` to find the correct service name and substitute it in the `MODEL_ENDPOINT` URL below.

    The first startup pulls the model weights and can take 5-15 minutes. Watch
    progress:

    ```bash
    oc logs --context="$CTX" -n gpt-oss-model -l serving.kserve.io/inferenceservice=gpt-oss -f
    ```

    Wait for `DeploymentReady=True`:

    ```bash
    oc wait --context="$CTX" --for=condition=Ready inferenceservice/gpt-oss \
      -n gpt-oss-model --timeout=900s
    ```

    ### 5. Get the endpoint URL

    ```bash
    URL=$(oc get inferenceservice gpt-oss --context="$CTX" -n gpt-oss-model \
      -o jsonpath='{.status.url}')
    echo "$URL"
    ```

    !!! warning "On RHOAI 3.x with Headless service config, the reported URL is missing the port"
        Many RHOAI 3.x DataScienceClusters set `kserve.rawDeploymentServiceConfig: Headless`. With Headless, the predictor Service has `ClusterIP: None`, DNS resolves directly to pod IPs, and the Service's `port: 80 -> targetPort: 8000` mapping doesn't apply — you must hit the pod's listening port (`:8000`) directly. The InferenceService's `.status.url` won't include it.

        Check with:

        ```bash
        oc get svc --context="$CTX" -n gpt-oss-model -l serving.kserve.io/inferenceservice=gpt-oss \
          -o jsonpath='{.items[0].spec.clusterIP}{"\n"}'
        ```

        If it prints `None`, append `:8000` to the URL — for example
        `http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local:8000`.

    ### 6. Smoke test

    RawDeployment + Headless doesn't expose a Route by default,
    so use port-forward:

    ```bash
    oc port-forward --context="$CTX" -n gpt-oss-model deployment/gpt-oss-predictor 18000:8000 &
    curl -s http://localhost:18000/v1/models | jq
    curl -s http://localhost:18000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "RedHatAI/gpt-oss-20b",
        "messages": [{"role": "user", "content": "In one short sentence, say hello."}],
        "max_tokens": 300
      }' | jq '.choices[0].message'
    kill %1
    ```

    You should see the registered model and a `content: "Hello!"` response
    with a populated `reasoning_content` field.

    !!! note "Reasoning content"
        gpt-oss-20b emits its chain-of-thought into a separate `reasoning_content` field on the response message. The visible `content` is the final answer only. If you ever see `content: null` with `finish_reason: "length"`, the response was truncated mid-reasoning — raise `max_tokens`.

### Export the environment variables

Set these variables for the rest of the tutorial. The values depend on how
you deployed the model.

=== "Catalog deploy"

    For **local development** (running the agent on your laptop), use the
    external route URL:

    ```bash
    export MODEL_ENDPOINT="https://redhataigpt-oss-20b-gpt-oss-model.apps.<your-cluster-domain>/v1"
    export MODEL_NAME="redhataigpt-oss-20b"
    export OPENAI_API_KEY="<token from dashboard>"
    ```

    For **deployed agents** on the cluster, use the internal service URL
    in your Helm values or ConfigMap:

    ```
    MODEL_ENDPOINT=https://redhataigpt-oss-20b-predictor.gpt-oss-model.svc.cluster.local:8443/v1
    ```

=== "Manual deploy"

    ```bash
    export MODEL_ENDPOINT="http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local:8000/v1"
    export MODEL_NAME="RedHatAI/gpt-oss-20b"
    export OPENAI_API_KEY="not-required"
    ```

    Adjust the host/port to match your cluster -- see the Headless service
    warning in the manual deploy tab above.

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
curl -s "$MODEL_ENDPOINT/models" \
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

### Path C: Models as a Service

If your cluster runs RHOAI 3.4+, you can serve models through the MaaS
gateway — centralized access with API keys, token-based quotas, and cost
visibility. See the [Models as a Service](../supplementary/maas-model-serving.md)
supplementary module after completing the core tutorial.

## Picking a different model

`RedHatAI/gpt-oss-20b` is the reference because it's reasoning-capable
with native tool calls, fits in ~16 GB of VRAM, and is what the
`workshop-setup-ogx` playbook validates end-to-end. Any
instruction-tuned model with reliable tool-calling support works,
though most won't share the reasoning-content split:

- **Granite 3.3 8B Instruct** (`ibm-granite/granite-3.3-8b-instruct`) — smaller (24 GB VRAM at fp16), no reasoning track, FIPS-friendly, gated on Hugging Face.
- **Llama 3.3 70B Instruct** — substantially larger; needs multi-GPU or aggressive quantization.
- **Mistral Large** — also large; tool calling reliable.

If you switch models, check vLLM's CLI args against the model's docs
(quantization, KV-cache dtype, max context). Smaller models (under
~7 B params) may struggle with tool-call JSON for some calculus tools.

## Next

[Install CLI Tools](install-cli-tools.md).
