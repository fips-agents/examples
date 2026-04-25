# Helm Chart Anatomy

The agent project includes a Helm chart in `chart/` that produces all the
Kubernetes resources needed to run on OpenShift. This page documents every
template, how `values.yaml` keys map to resource fields, and the patterns the
chart uses to handle rolling updates and optional sidecars.

## Chart metadata

`Chart.yaml` identifies the chart to Helm.

```yaml
apiVersion: v2
name: ecosystem-test-agent
description: Helm chart for deploying a BaseAgent to OpenShift
version: 0.6.0
appVersion: 0.6.0
type: application
```

!!! note "Chart name vs. your agent name"
    The chart is named `ecosystem-test-agent` because it ships with the
    template's default. When you scaffold your own agent with
    `fips-agents create agent calculus-agent`, the chart name matches your
    project. The template helpers (`ecosystem-test-agent.fullname`, etc.)
    would be named after your chart instead.

`version` tracks the chart itself. `appVersion` tracks the agent image and
appears in the `app.kubernetes.io/version` label on every resource.

## Template helpers (`_helpers.tpl`)

The chart defines four named templates that other templates reference with
`include`. Understanding these is essential for reading the rest of the chart.

| Template | Output |
|----------|--------|
| `ecosystem-test-agent.name` | `.Chart.Name`, overridden by `nameOverride`. Truncated to 63 characters. |
| `ecosystem-test-agent.fullname` | `<release>-<name>`, overridden by `fullnameOverride`. Truncated to 63 characters. If the release name already contains the chart name, only the release name is used. |
| `ecosystem-test-agent.labels` | Full label set: chart version, selector labels, `app.kubernetes.io/version`, `app.kubernetes.io/managed-by`. |
| `ecosystem-test-agent.selectorLabels` | Minimal label set for `matchLabels`: `app.kubernetes.io/name` and `app.kubernetes.io/instance`. |
| `ecosystem-test-agent.chart` | `<name>-<version>` string for the `helm.sh/chart` label. |

### Name override behavior

| `nameOverride` | `fullnameOverride` | Resulting fullname |
|----------------|--------------------|--------------------|
| `""` (default) | `""` (default) | `<release>-ecosystem-test-agent` |
| `"my-agent"` | `""` | `<release>-my-agent` |
| any | `"custom"` | `custom` |

## ConfigMap

**Template:** `templates/configmap.yaml`

Produces a ConfigMap named `<fullname>-config`. Every key under
`values.config` becomes a key-value pair in the ConfigMap's `data` section.

```yaml
# values.yaml
config:
  MODEL_ENDPOINT: https://vllm.apps.cluster.example.com/v1
  MODEL_NAME: meta-llama/Llama-3.3-70B-Instruct
  MAX_ITERATIONS: "50"
```

Produces:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: release-ecosystem-test-agent-config
data:
  MODEL_ENDPOINT: "https://vllm.apps.cluster.example.com/v1"
  MODEL_NAME: "meta-llama/Llama-3.3-70B-Instruct"
  MAX_ITERATIONS: "50"
```

All values are quoted in the template (`{{ $value | quote }}`), so numeric
strings like `"50"` are preserved correctly.

### values.yaml keys

| Key | Type | Description |
|-----|------|-------------|
| `config.<NAME>` | string | Injected as env var `<NAME>` into the agent container via `envFrom`. |

As of v0.11.0, the following ConfigMap keys control the observability and
storage features added in that release:

| Key | Description | Default (if unset) |
|-----|-------------|--------------------|
| `STORAGE_BACKEND` | Persistence backend for sessions and traces (`null`, `sqlite`, `postgres`) | `null` |
| `SESSIONS_ENABLED` | Enable session persistence | `false` |
| `TRACES_ENABLED` | Enable trace collection | `false` |
| `METRICS_ENABLED` | Enable Prometheus metrics at `/metrics` | `false` |

!!! tip "Prompts are not in ConfigMaps"
    Prompts, rules, and skills are baked into the container image, not injected
    via ConfigMaps. This provides version traceability -- the image SHA pins the
    exact prompt text. Only runtime-variable values (endpoints, model names, log
    levels) belong in the ConfigMap.

## Deployment

**Template:** `templates/deployment.yaml`

This is the most complex template. It produces a Deployment with one required
container (the agent) and one optional container (the code-execution sandbox).

### Pod-level settings

```yaml
spec:
  replicas: {{ .Values.replicaCount }}
  # ...
  template:
    metadata:
      annotations:
        checksum/config: {{ include ... | sha256sum }}
    spec:
      securityContext:
        runAsNonRoot: true
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `replicaCount` | `spec.replicas` | `1` |

The pod-level `securityContext` enforces `runAsNonRoot: true`, which satisfies
the OpenShift `restricted-v2` SCC.

### ConfigMap checksum annotation

```yaml
annotations:
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

This annotation contains a SHA-256 hash of the rendered ConfigMap. When a
ConfigMap value changes (e.g., you update `MODEL_NAME` in `values.yaml`), the
hash changes, which changes the pod template, which triggers a rolling update.

Without this annotation, updating only the ConfigMap would leave existing pods
running with stale environment variables until they are manually restarted.
Helm does not natively restart pods on ConfigMap changes -- this checksum
pattern is the standard workaround.

### Agent container

```yaml
containers:
  - name: agent
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
    imagePullPolicy: {{ .Values.image.pullPolicy }}
    ports:
      - name: http
        containerPort: {{ .Values.service.port }}
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `image.repository` | `image` (name portion) | `ecosystem-test-agent` |
| `image.tag` | `image` (tag portion) | `latest` |
| `image.pullPolicy` | `imagePullPolicy` | `IfNotPresent` |
| `service.port` | `containerPort` | `8080` |
| `resources.requests.cpu` | `resources.requests.cpu` | `100m` |
| `resources.requests.memory` | `resources.requests.memory` | `256Mi` |
| `resources.limits.cpu` | `resources.limits.cpu` | `500m` |
| `resources.limits.memory` | `resources.limits.memory` | `512Mi` |

The container's `securityContext` drops all capabilities and disallows
privilege escalation:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
```

### Environment injection

Environment variables reach the agent container through two paths:

1. **`envFrom`** -- All keys from the ConfigMap are injected as env vars.
2. **`env`** -- Additional variables from `values.env` (for Secret references
   or values outside the config section) and, when the sandbox is enabled, the
   `SANDBOX_URL` variable.

```yaml
# values.yaml -- referencing a Secret
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: agent-secrets
        key: api-key
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `env` | `spec.containers[agent].env` | `[]` |

### Health probes

Probes are disabled by default. When enabled, the agent must expose `/healthz`
and `/readyz` endpoints on the service port.

```yaml
# values.yaml
probes:
  enabled: true
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `probes.enabled` | Controls presence of `livenessProbe`/`readinessProbe` | `false` |

When enabled, the probe configuration is:

| Probe | Path | Initial delay | Period |
|-------|------|---------------|--------|
| Liveness | `/healthz` | 10s | 30s |
| Readiness | `/readyz` | 5s | 10s |

### Sandbox sidecar (conditional)

When `sandbox.enabled` is `true`, a second container is added to the pod. This
container runs the code-execution sandbox, which the agent's `code_executor`
tool reaches at `localhost:8000` (pods share a network namespace).

The entire sidecar block is wrapped in `{{- if .Values.sandbox.enabled }}`.
When disabled (the default), no sandbox container, volumes, or env vars are
added -- the Deployment produces a single-container pod.

#### What changes when `sandbox.enabled: true`

1. A `sandbox` container is added to `spec.containers`.
2. `SANDBOX_URL=http://localhost:8000` is injected into the agent container's `env`.
3. A `sandbox-tmp` emptyDir volume is added to `spec.volumes` and mounted at `/tmp` in the sandbox container.
4. The sandbox container gets its own liveness and readiness probes on port 8000.

#### Sandbox container configuration

```yaml
- name: sandbox
  image: "{{ .Values.sandbox.image.repository }}:{{ .Values.sandbox.image.tag }}"
  env:
    - name: SANDBOX_PROFILE
      value: {{ .Values.sandbox.profile | quote }}
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `sandbox.enabled` | Controls presence of the sidecar | `false` |
| `sandbox.profile` | `SANDBOX_PROFILE` env var | `minimal` |
| `sandbox.image.repository` | Sandbox container image name | `code-sandbox` |
| `sandbox.image.tag` | Sandbox container image tag | `latest` |
| `sandbox.image.pullPolicy` | Sandbox `imagePullPolicy` | `IfNotPresent` |
| `sandbox.resources.requests.cpu` | Sandbox CPU request | `100m` |
| `sandbox.resources.requests.memory` | Sandbox memory request | `128Mi` |
| `sandbox.resources.limits.cpu` | Sandbox CPU limit | `500m` |
| `sandbox.resources.limits.memory` | Sandbox memory limit | `256Mi` |

The sandbox container enforces `readOnlyRootFilesystem: true`. The only
writable path is the emptyDir at `/tmp`, capped at 10Mi.

Available profiles: `minimal`, `data-science`, `financial`, `code-analysis`.
The profile controls which imports are allowed and which scan stages run
inside the sandbox.

#### Seccomp profile (optional)

When `sandbox.seccomp.enabled` is `true`, a Localhost seccomp profile is
attached to the sandbox container:

```yaml
seccompProfile:
  type: Localhost
  localhostProfile: operator/<fullname>-sandbox.json
```

This profile blocks networking syscalls (`socket`, `connect`, `bind`) and
dangerous operations (`ptrace`, `mount`, `io_uring`) at the kernel level.

Prerequisites:

- Security Profiles Operator (SPO) installed on the cluster (GA since OCP 4.12).
- A custom SCC or SPO ProfileBinding that permits Localhost seccomp profiles
  (the default `restricted-v2` SCC only allows `RuntimeDefault`).

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `sandbox.seccomp.enabled` | Controls presence of `seccompProfile` on sandbox container | `false` |

### LLM adapter sidecar (conditional)

When `llm_adapter.enabled` is `true` (or when `ADAPTER_PROVIDER` is set in
the ConfigMap), a second sidecar container is added to the pod. This container
runs the LLM adapter, which translates OpenAI-compatible requests to other
provider APIs. The agent reaches it at `localhost:8081` (pods share a network
namespace).

The entire sidecar block is wrapped in `{{- if .Values.llm_adapter.enabled }}`.
When disabled (the default), no adapter container or env vars are added.

#### What changes when `llm_adapter.enabled: true`

1. An `llm-adapter` container is added to `spec.containers`.
2. Provider-specific env vars are injected into the adapter container (e.g.,
   `ADAPTER_PROVIDER`, `ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID`,
   `AZURE_OPENAI_ENDPOINT`).
3. Liveness and readiness probes target `localhost:8081/healthz`.

The adapter supports 8 providers: Anthropic, Bedrock (Claude), Bedrock
Converse, Azure OpenAI, OpenAI-compatible, Ollama, llama.cpp, and Vertex
AI/Gemini.

The agent's `model.provider` in `agent.yaml` should match the adapter
provider so that BaseAgent sends requests to `localhost:8081` in the correct
format.

#### LLM adapter container configuration

```yaml
- name: llm-adapter
  image: "{{ .Values.llm_adapter.image.repository }}:{{ .Values.llm_adapter.image.tag }}"
  ports:
    - name: adapter
      containerPort: 8081
  livenessProbe:
    httpGet:
      path: /healthz
      port: 8081
    initialDelaySeconds: 5
    periodSeconds: 30
  readinessProbe:
    httpGet:
      path: /healthz
      port: 8081
    initialDelaySeconds: 3
    periodSeconds: 10
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop:
        - ALL
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `llm_adapter.enabled` | Controls presence of the sidecar | `false` |
| `llm_adapter.image.repository` | Adapter container image name | `llm-adapter` |
| `llm_adapter.image.tag` | Adapter container image tag | `latest` |
| `llm_adapter.image.pullPolicy` | Adapter `imagePullPolicy` | `IfNotPresent` |
| `llm_adapter.resources.requests.cpu` | Adapter CPU request | `100m` |
| `llm_adapter.resources.requests.memory` | Adapter memory request | `128Mi` |
| `llm_adapter.resources.limits.cpu` | Adapter CPU limit | `500m` |
| `llm_adapter.resources.limits.memory` | Adapter memory limit | `256Mi` |

#### values.yaml defaults

```yaml
llm_adapter:
  enabled: false
  image:
    repository: llm-adapter
    tag: latest
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

## Service

**Template:** `templates/service.yaml`

Produces a ClusterIP Service that routes traffic to pods matching the selector
labels.

```yaml
spec:
  type: ClusterIP
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `service.port` | `spec.ports[0].port` | `8080` |

The `targetPort` is the named port `http` defined in the Deployment's
container spec, so they stay in sync automatically.

## Route

**Template:** `templates/route.yaml`

Produces an OpenShift Route. The entire template is wrapped in
`{{- if .Values.route.enabled }}`, so no Route is created by default.

```yaml
spec:
  to:
    kind: Service
    name: {{ include "ecosystem-test-agent.fullname" . }}
    weight: 100
  port:
    targetPort: http
  tls:
    termination: {{ .Values.route.tls.termination }}
    insecureEdgeTerminationPolicy: {{ .Values.route.tls.insecureEdgeTerminationPolicy }}
```

| values.yaml key | Resource field | Default |
|-----------------|----------------|---------|
| `route.enabled` | Controls whether the Route is created | `false` |
| `route.host` | `spec.host` (omitted if empty) | `""` |
| `route.tls.termination` | `spec.tls.termination` | `edge` |
| `route.tls.insecureEdgeTerminationPolicy` | `spec.tls.insecureEdgeTerminationPolicy` | `Redirect` |

When `route.host` is empty, OpenShift auto-generates a hostname from the Route
name and the cluster's wildcard domain (e.g.,
`release-ecosystem-test-agent.apps.cluster.example.com`).

## FIPS compatibility

No FIPS-specific chart configuration is required. The UBI base images ship
FIPS-aware OpenSSL and automatically respect the host kernel's `fips=1` mode.
See the comments in `values.yaml` for validated behavior details.
