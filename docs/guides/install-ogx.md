# Install OGX

[OGX](https://ogx-ai.github.io/) is the rebrand of [LlamaStack](https://github.com/meta-llama/llama-stack) — an open-source AI application server that fronts inference, vector stores, safety shields, MCP tool orchestration, and the OpenAI Responses API behind a single OpenAI-compatible HTTP endpoint.

Modules 1–9 talk to vLLM directly: the agent's `MODEL_ENDPOINT` resolves to a KServe `InferenceService` and the agent runs its own MCP tool loop in `step()`. Module 10 introduces **platform mode**, where the agent talks to OGX instead, and OGX handles MCP tool calls, shield enforcement, and the inference loop server-side.

This guide installs the upstream OGX Operator and creates a minimal distribution that points at your existing vLLM. Subsequent guides layer in shields and observability.

!!! note "When you need this"
    You only need OGX if you're working through Module 10. Modules 1–9 don't depend on it.

!!! warning "The OGX rebrand is in flight"
    The project is being renamed from "LlamaStack" to "OGX," and the **docs site has shipped the new names ahead of the code**. As of v0.9.0 — the latest release — the operator binary, CRDs, and namespace still use the `llama-stack-*` / `llamastack.io` names. This guide uses the names that **actually work today**. When the upstream rename lands in a release, we'll update the kind, apiVersion, namespace, and operator deployment name in lockstep.

## Prerequisites

- [OpenShift AI installed](install-openshift-ai.md), with vLLM serving a model per [Serve an LLM](serve-an-llm.md)
- `oc` logged in to the cluster with `cluster-admin` rights (the operator install creates cluster-scoped resources)
- The in-cluster `MODEL_ENDPOINT` and `MODEL_NAME` from Serve an LLM. Those exact values become `VLLM_URL` and `VLLM_INFERENCE_MODEL` in the `LlamaStackDistribution` below — the `/v1` suffix on the URL is required (see warning in Step 4).

## 1. Install the OGX Operator

The operator is distributed as a single manifest (no OperatorHub package yet — track [ogx-k8s-operator](https://github.com/ogx-ai/ogx-k8s-operator) for OLM-bundled releases).

Pin to a tagged release:

```bash
OGX_OPERATOR_VERSION=v0.9.0
oc apply -f https://raw.githubusercontent.com/ogx-ai/ogx-k8s-operator/${OGX_OPERATOR_VERSION}/release/operator.yaml
```

The operator runs in `llama-stack-k8s-operator-system`. Wait for it to come up:

```bash
oc rollout status deployment/llama-stack-k8s-operator-controller-manager \
  -n llama-stack-k8s-operator-system --timeout=180s
```

Verify the CRD is registered:

```bash
oc get crd llamastackdistributions.llamastack.io
```

## 2. Create a namespace for OGX

```bash
oc new-project ogx
```

## 3. Author the run-config ConfigMap

OGX needs a `run.yaml` that registers the vLLM provider and the model it serves. The starter image bundles a default `run.yaml`, but its `registered_resources.models` list is hardcoded empty — and OGX has no runtime model-registration endpoint, so we must declare the model up front.

The minimum viable config registers one inference provider (your vLLM) and one model. [Configure Safety Shields](configure-shields.md) extends this same ConfigMap with shields, vector DBs, and MCP connectors.

Save as `ogx-config.yaml`:

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
      - tool_runtime
    providers:
      inference:
        - provider_id: vllm
          provider_type: remote::vllm
          config:
            base_url: ${env.VLLM_URL:=}
            max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
            api_token: ${env.VLLM_API_TOKEN:=fake}
    registered_resources:
      models:
        - model_id: ${env.VLLM_INFERENCE_MODEL}
          provider_id: vllm
          model_type: llm
      shields: []
      tool_groups: []
    server:
      port: 8321
```

```bash
oc apply -f ogx-config.yaml
```

The `${env.X}` syntax is OGX's runtime substitution — values come from the operator's `containerSpec.env` (which we set in the next step). Defaults apply when an env var is unset.

## 4. Create the `LlamaStackDistribution`

The Operator turns this CR into a `Deployment`, `Service`, and `PersistentVolumeClaim`, mounting the ConfigMap at `/etc/llama-stack/config.yaml`. Save as `ogx-distribution.yaml`:

```yaml
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  name: ogx
  namespace: ogx
spec:
  replicas: 1
  server:
    distribution:
      name: starter
    userConfig:
      configMapName: ogx-config
    containerSpec:
      port: 8321
      env:
        - name: VLLM_URL
          value: "http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local:8000/v1"
        - name: VLLM_INFERENCE_MODEL
          value: "RedHatAI/gpt-oss-20b"
        - name: VLLM_MAX_TOKENS
          value: "4096"
        - name: VLLM_API_TOKEN
          value: "fake"
    storage:
      size: "20Gi"
      mountPath: "/home/lls/.lls"
  network:
    allowedFrom:
      namespaces:
        - "*"
```

Three things to swap for your cluster:

- **`VLLM_URL`** — internal URL of the vLLM service from [Serve an LLM](serve-an-llm.md), **including the `/v1` suffix**. OGX uses this verbatim as the OpenAI client's `base_url`. The exact host:port depends on your KServe service config — see the warning below.
- **`VLLM_INFERENCE_MODEL`** — the served model name vLLM advertises (the same value you set as `MODEL_NAME`).
- **`VLLM_API_TOKEN`** — leave as `"fake"` for an unauthenticated in-cluster vLLM. If your vLLM is behind an auth layer, set the real token.

!!! warning "Three settings the upstream docs get wrong — don't copy them"
    1. Use `kind: LlamaStackDistribution` and `apiVersion: llamastack.io/v1alpha1`, **not** `OGXDistribution` / `ogx.io/v1alpha1`. The rebrand hasn't shipped in the operator code yet.
    2. Always set `spec.network.allowedFrom.namespaces: ["*"]`. Omit it and the operator applies a default-deny policy that blocks the OpenShift router from reaching the pod — your Route hangs with no diagnostic. Tighten per cluster as needed; `["*"]` is the right starting point for a tutorial.
    3. `VLLM_URL` must include `/v1`. Several upstream docs and reference configs show the URL without it, but the OpenAI client OGX uses internally appends `/chat/completions` literally — drop the `/v1` and every chat completion returns vLLM's 404.

!!! note "vLLM service URL format depends on KServe service config"
    Many RHOAI 3.x clusters set `kserve.rawDeploymentServiceConfig: Headless` in the DataScienceCluster. With Headless, the predictor Service has `ClusterIP: None`, DNS resolves directly to pod IPs, and the Service's `port: 80 → targetPort: 8000` mapping doesn't apply — you must include `:8000` in `VLLM_URL` (or whatever port your vLLM container listens on). Without Headless, port 80 works and `:8000` is unnecessary. Check with `oc get svc <predictor> -n <ns> -o jsonpath='{.spec.clusterIP}'` — `None` means Headless.

Apply it:

```bash
oc apply -f ogx-distribution.yaml
```

The operator creates a `Deployment` named `ogx` and a `Service` exposing port 8321. Wait for it:

```bash
oc rollout status deployment/ogx -n ogx --timeout=300s
```

## 5. Expose the endpoint

For agents running in the cluster, the service URL is enough. The operator names the Service `<distribution-name>-service`:

```
http://ogx-service.ogx.svc.cluster.local:8321
```

For local testing with `curl`, expose a Route. OGX with a reasoning model like gpt-oss can take longer than the default 30 s to reply — set a 300 s router timeout:

```bash
oc create route edge ogx --service=ogx-service --port=8321 -n ogx
oc annotate route ogx -n ogx haproxy.router.openshift.io/timeout=300s
OGX_ENDPOINT="https://$(oc get route ogx -n ogx -o jsonpath='{.spec.host}')/v1"
echo "$OGX_ENDPOINT"
```

## 6. Smoke test

OGX exposes the OpenAI-compatible API plus its own native APIs under `/v1`:

```bash
# Should list your registered model as `vllm/<model-id>`
curl -s "$OGX_ENDPOINT/models" | jq '.data[] | {id, custom_metadata}'

# Native — should return [] until you register shields (see Configure Safety Shields)
curl -s "$OGX_ENDPOINT/shields" | jq
```

The expected `/models` output:

```json
{
  "id": "vllm/RedHatAI/gpt-oss-20b",
  "custom_metadata": {
    "model_type": "llm",
    "provider_id": "vllm",
    "provider_resource_id": "RedHatAI/gpt-oss-20b"
  }
}
```

!!! warning "Models are exposed as `<provider_id>/<model_id>`, not the bare model id"
    OGX prefixes registered models with their provider id. Our `RedHatAI/gpt-oss-20b` registered through the `vllm` provider becomes `vllm/RedHatAI/gpt-oss-20b` externally. Querying with the bare `RedHatAI/gpt-oss-20b` returns 404 because OGX splits on the first `/` to find a provider named `RedHatAI`.

A round-trip inference call confirms the path through OGX → vLLM:

```bash
curl -s "$OGX_ENDPOINT/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vllm/RedHatAI/gpt-oss-20b",
    "messages": [{"role": "user", "content": "Say hi."}],
    "max_tokens": 300
  }' | jq '.choices[0].message.content'
```

If you get a response, OGX is wired to vLLM correctly.

!!! note "Reasoning models emit a `reasoning_content` field"
    gpt-oss models stream their chain-of-thought into a separate `reasoning_content` field on the response message. The visible `content` is the final answer only. If a smoke test returns `content: null` with `finish_reason: "length"`, raise `max_tokens` — reasoning ate the budget.

## 7. Export for Module 10

```bash
export MODEL_ENDPOINT="$OGX_ENDPOINT"
export MODEL_NAME="vllm/$MODEL_NAME"
```

Module 10 reads `MODEL_ENDPOINT` and `MODEL_NAME` the same way Modules 1–9 do — only the values change. Note the `vllm/` prefix on `MODEL_NAME` from the section above; without it the agent's chat completions will 404.

## Next

- [Configure Safety Shields](configure-shields.md) — extend the `ogx-config` ConfigMap to register shields, vector DBs, and MCP toolgroups. This is where the `code-scanner` shield becomes usable.
- [Observability Backends](observability-backends.md) — wire OGX's OTLP exporter to a trace receiver
- Then **[Module 10: Guardrails and Observability](../10-guardrails-and-observability.md)**

## Further reading

- [OGX architecture](https://ogx-ai.github.io/docs/concepts/architecture)
- [llama-stack-k8s-operator (the operator we install above)](https://github.com/ogx-ai/ogx-k8s-operator)
- [`workshop-setup-ogx`](https://github.com/rdwj/workshop-setup-ogx) — the Ansible-driven equivalent of this guide, plus a 12-layer smoke-test plan and the upstream-issues list this guide draws its corrections from
- [LlamaStack → OGX rebrand](https://ogx-ai.github.io/blog/from-llama-stack-to-ogx)
