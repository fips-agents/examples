# Install OGX

[OGX](https://ogx-ai.github.io/) is the rebrand of [LlamaStack](https://github.com/meta-llama/llama-stack) — an open-source AI application server that fronts inference, vector stores, safety shields, MCP tool orchestration, and the OpenAI Responses API behind a single OpenAI-compatible HTTP endpoint.

Modules 1–9 talk to vLLM directly: the agent's `MODEL_ENDPOINT` resolves to a KServe `InferenceService` and the agent runs its own MCP tool loop in `step()`. Module 10 introduces **platform mode**, where the agent talks to OGX instead, and OGX handles MCP tool calls, shield enforcement, and the inference loop server-side.

This guide installs the OGX Kubernetes Operator and creates a minimal `OGXDistribution` that points at your existing vLLM. Subsequent guides layer in shields and observability.

!!! note "When you need this"
    You only need OGX if you're working through Module 10. Modules 1–9 don't depend on it.

## Prerequisites

- [OpenShift AI installed](install-openshift-ai.md), with vLLM serving a model per [Serve an LLM](serve-an-llm.md)
- `oc` logged in to the cluster with `cluster-admin` rights (the operator install creates cluster-scoped resources)
- The `MODEL_ENDPOINT` and `MODEL_NAME` you exported in Serve an LLM

## 1. Install the OGX Operator

The operator is distributed as a single manifest (no OperatorHub package yet — track [ogx-k8s-operator](https://github.com/ogx-ai/ogx-k8s-operator) for OLM-bundled releases).

Pin to a tagged release:

```bash
OGX_OPERATOR_VERSION=v0.4.0
oc apply -f https://raw.githubusercontent.com/ogx-ai/ogx-k8s-operator/${OGX_OPERATOR_VERSION}/release/operator.yaml
```

The operator runs in `ogx-k8s-operator-system`. Wait for it to come up:

```bash
oc rollout status deployment/ogx-k8s-operator-controller-manager \
  -n ogx-k8s-operator-system --timeout=180s
```

Verify the CRDs are registered:

```bash
oc get crd ogxdistributions.ogx.io
```

## 2. Create a namespace for OGX

```bash
oc new-project ogx
```

## 3. Author the OGX `config.yaml`

OGX is configured by a `config.yaml` mounted via ConfigMap. The minimal config for this tutorial registers one inference provider (your existing vLLM) and one telemetry exporter. Shields and MCP connectors are added by subsequent guides.

Save as `ogx-config.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ogx-config
  namespace: ogx
data:
  config.yaml: |
    version: '2'
    image_name: tutorial

    apis:
      - inference
      - safety
      - tool_runtime
      - telemetry

    providers:
      inference:
        - provider_id: vllm
          provider_type: remote::vllm
          config:
            url: ${env.VLLM_URL}
            max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
            api_token: ${env.VLLM_API_TOKEN:=fake}

      telemetry:
        - provider_id: otel
          provider_type: inline::meta-reference
          config:
            service_name: ogx
            sinks: console,otel_trace,otel_metric
            otel_endpoint: ${env.OTEL_EXPORTER_OTLP_ENDPOINT:=http://otel-collector.observability.svc.cluster.local:4318}

    models:
      - model_id: ${env.INFERENCE_MODEL}
        provider_id: vllm
        model_type: llm

    shields: []
    tool_groups: []
```

The `${env.X}` syntax is OGX's runtime substitution — values come from the operator's `containerSpec.env`. Defaults apply when the env var is unset.

Apply it:

```bash
oc apply -f ogx-config.yaml
```

## 4. Create the `OGXDistribution`

The Operator turns this CR into a `Deployment`, `Service`, and `PersistentVolumeClaim`. Save as `ogx-distribution.yaml`:

```yaml
apiVersion: ogx.io/v1alpha1
kind: OGXDistribution
metadata:
  name: ogx
  namespace: ogx
spec:
  replicas: 1
  server:
    distribution:
      image: docker.io/llamastack/distribution-starter:latest
    containerSpec:
      port: 8321
      env:
        - name: VLLM_URL
          value: "http://granite-predictor.model-serving.svc.cluster.local/v1"
        - name: INFERENCE_MODEL
          value: "ibm-granite/granite-3.3-8b-instruct"
        - name: VLLM_API_TOKEN
          value: "fake"
    userConfig:
      configMap:
        name: ogx-config
    storage:
      size: "10Gi"
      mountPath: "/home/lls/.lls"
```

Two things to swap for your cluster:

- `VLLM_URL` — internal URL of the vLLM `InferenceService` from [Serve an LLM](serve-an-llm.md). The hostname follows `<service>.<namespace>.svc.cluster.local`.
- `INFERENCE_MODEL` — the served model name vLLM advertises (the same value you set as `MODEL_NAME`).

The `image: docker.io/llamastack/distribution-starter:latest` reference still uses the `llamastack/` namespace; the rebrand to `ogx-ai/` is in flight upstream.

Apply it:

```bash
oc apply -f ogx-distribution.yaml
```

The operator creates a `Deployment` named `ogx` and a `Service` exposing port 8321. Wait for it:

```bash
oc rollout status deployment/ogx -n ogx --timeout=300s
```

## 5. Expose the endpoint

For agents running in the cluster, the service URL is enough:

```
http://ogx.ogx.svc.cluster.local:8321/v1
```

For local testing with `curl` or `pytest`, expose a Route:

```bash
oc create route edge ogx --service=ogx --port=8321 -n ogx
OGX_ENDPOINT="https://$(oc get route ogx -n ogx -o jsonpath='{.spec.host}')/v1"
echo "$OGX_ENDPOINT"
```

## 6. Smoke test

OGX exposes the OpenAI-compatible API plus its own native APIs under `/v1`. Hit two of each:

```bash
# OpenAI-compatible — should return your registered vLLM model
curl -s "$OGX_ENDPOINT/models" | jq

# Native — should return [] until you register shields
curl -s "$OGX_ENDPOINT/shields" | jq
```

A round-trip inference call confirms the path through OGX → vLLM:

```bash
curl -s "$OGX_ENDPOINT/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ibm-granite/granite-3.3-8b-instruct",
    "messages": [{"role": "user", "content": "Say hi."}]
  }' | jq -r '.choices[0].message.content'
```

If you get a response, OGX is wired to vLLM correctly.

## 7. Export for Module 10

```bash
export OGX_ENDPOINT="$OGX_ENDPOINT"
```

Module 10 reads this as the agent's `MODEL_ENDPOINT` (the agent talks to OGX instead of vLLM directly).

## Next

- [Configure Safety Shields](configure-shields.md) — register shields server-side so platform mode can enforce them
- [Observability Backends](observability-backends.md) — wire OGX's OTLP exporter to a trace receiver
- Then **[Module 10: Guardrails and Observability](../10-guardrails-and-observability.md)**

## Further reading

- [OGX architecture](https://ogx-ai.github.io/docs/concepts/architecture)
- [OGX Kubernetes deployment](https://ogx-ai.github.io/docs/deploying/kubernetes_deployment)
- [LlamaStack → OGX rebrand](https://ogx-ai.github.io/blog/from-llama-stack-to-ogx)
