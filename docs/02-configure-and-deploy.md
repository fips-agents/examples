# Module 2: Configure and Deploy to OpenShift

Now that you understand the project layout, it is time to find your model
endpoint, configure the agent, and deploy it to OpenShift. By the end of
this module your agent will be running in a pod, reachable over HTTPS, and
answering questions using your LLM.

## Find your model values

The agent needs three values to connect to your LLM. How you find them
depends on how the model was deployed. This is a practical exercise in
navigating OpenShift -- a skill you'll use throughout your work with the
platform.

### MODEL_ENDPOINT

The URL where your model is listening for OpenAI-compatible API requests.

=== "Catalog deploy (RHOAI dashboard)"

    1. Open the RHOAI dashboard
    2. Navigate to **Models > Deployed models**
    3. Click on your deployed model
    4. Under **Inference endpoints**, find the **Internal** URL
    5. Append `/v1` to get the full endpoint, for example:

            https://redhataigpt-oss-20b-predictor.gpt-oss-model.svc.cluster.local:8443/v1

=== "Manual deploy (CLI)"

    Find the InferenceService and construct the URL from its name and
    namespace:

    ```bash
    oc get inferenceservice -A --context="$CTX"
    ```

    The internal service URL follows the pattern:

        http://<name>-predictor.<namespace>.svc.cluster.local:8000/v1

    !!! warning "Headless service port"
        If your DataScienceCluster uses `rawDeploymentServiceConfig: Headless`,
        you must include `:8000` in the URL. The InferenceService's
        `.status.url` omits it. See the
        [Serve an LLM](guides/serve-an-llm.md) guide for details.

=== "Instructor-provided or external"

    Your instructor or provider will give you the endpoint URL. It should
    end with `/v1` (e.g. `https://api.example.com/v1`).

### MODEL_NAME

The model identifier that the inference server expects.

- **Catalog deploy**: Click your model in the RHOAI dashboard. The name
  shown is the model ID -- typically a slug like `redhataigpt-oss-20b`
  (not the Hugging Face path). You can also query it:

        curl -sk <your-endpoint>/models -H "Authorization: Bearer <token>" | jq '.data[].id'

- **Manual deploy**: Usually the Hugging Face model ID, e.g.
  `RedHatAI/gpt-oss-20b`.
- **External**: Whatever your provider calls the model.

### OPENAI_API_KEY

An authentication token for the model endpoint.

- **Catalog deploy**: Find the service account token in the RHOAI
  dashboard under your model's **Inference endpoints** section.
- **Manual deploy**: vLLM doesn't require authentication by default.
  Set this to `not-required` -- the OpenAI Python SDK requires a
  non-empty value even for unauthenticated endpoints.
- **External**: Your API key from the provider.

---

Note these three values -- you'll use them in the Helm deploy step below.

## Set agent identity

The `agent:` section at the top of `agent.yaml` controls metadata that appears
in logs and the `/v1/agent-info` endpoint. Update it to describe your agent:

```yaml
agent:
  name: ${AGENT_NAME:-calculus-agent}
  description: "A math tutor agent that solves calculus problems step by step"
  version: 0.1.0
```

The `name` and `description` are surfaced by the `/v1/agent-info` REST
endpoint, which is useful for service discovery when you have many agents
running in a cluster.

## Understanding the Helm chart

The `chart/` directory contains a Helm chart that produces the Kubernetes
resources your agent needs. Here is what each template creates:

| Template | Kubernetes Resource | Purpose |
|----------|-------------------|---------|
| `deployment.yaml` | Deployment | Pod spec, container image, env vars from ConfigMap |
| `service.yaml` | Service | ClusterIP exposing port 8080 inside the cluster |
| `configmap.yaml` | ConfigMap | Env vars built from `values.config` entries |
| `route.yaml` | Route (OpenShift) | External HTTPS access with TLS edge termination |

!!! info "What is a Helm chart?"
    Helm is a package manager for Kubernetes. A chart is a collection of
    templated YAML files that produce Kubernetes resources when rendered. You
    override template variables at deploy time with `--set key=value` flags or
    a custom values file. Think of it as `docker-compose.yml` but for
    Kubernetes.

### Key values in `values.yaml`

Open `chart/values.yaml` to see the full set of knobs. The ones you will use
most often:

**`image.repository` and `image.tag`** -- where Kubernetes pulls the container
image from. When using the OpenShift internal registry, this is the image
stream path (e.g. `image-registry.openshift-image-registry.svc:5000/calculus-agent/calculus-agent`).

**`config.*`** -- every key under `config:` becomes an environment variable in
the ConfigMap. These are substituted into `agent.yaml` at runtime. For example,
setting `config.MODEL_ENDPOINT` overrides the `${MODEL_ENDPOINT}` placeholder.

**`route.enabled`** -- when `true`, the chart creates an OpenShift Route that
gives your agent an external HTTPS URL. When `false`, the agent is only
reachable inside the cluster via its Service.

**`resources`** -- CPU and memory requests/limits. The defaults (100m CPU,
256Mi memory) are reasonable because the agent is I/O-bound: it spends most
of its time waiting for LLM responses over the network.

## Deploy to OpenShift

First, create the namespace where the agent will be deployed:

```bash
oc new-project calculus-agent --context="$CTX"
```

This creates the `calculus-agent` namespace and sets up the necessary
service accounts for builds and deployments.

Deploying the agent requires three operations: build the container image
in the cluster, resolve the image registry path, and install the Helm
chart. MCP servers (Module 3) can use `fips-agents deploy` for all of
this in one command, but agent projects currently require the manual
steps below.

### Build the container image

Create a binary BuildConfig that accepts source uploads, then start
the build:

```bash
# Create the BuildConfig
oc new-build --binary --name=calculus-agent --strategy=docker \
  -n calculus-agent --context="$CTX"

# Point it at the Containerfile
oc patch bc/calculus-agent --type=json \
  -p '[{"op":"replace","path":"/spec/strategy/dockerStrategy/dockerfilePath","value":"Containerfile"}]' \
  -n calculus-agent --context="$CTX"

# Upload source and build
oc start-build calculus-agent --from-dir=. --follow \
  -n calculus-agent --context="$CTX"
```

The build runs server-side on x86_64 — no architecture mismatches
regardless of your laptop.

### Deploy with Helm

Resolve the ImageStream to get the internal registry path, then install
the chart with your model values:

```bash
IMAGE=$(oc get is calculus-agent -n calculus-agent --context="$CTX" \
  -o jsonpath='{.status.dockerImageRepository}')

helm install calculus-agent chart/ \
  --set image.repository=$IMAGE \
  --set image.tag=latest \
  --set image.pullPolicy=Always \
  --set config.MODEL_ENDPOINT="<your-model-endpoint>" \
  --set config.MODEL_NAME="<your-model-name>" \
  --set config.OPENAI_API_KEY="<your-api-key-or-token>" \
  --set route.enabled=true \
  -n calculus-agent --kube-context="$CTX"
```

Replace the `<placeholder>` values with the three values you found above.

The `--set config.*` flags create a Kubernetes ConfigMap with these
key-value pairs. When the pod starts, fipsagents reads `agent.yaml`,
finds `${MODEL_ENDPOINT:-...}`, and substitutes the value from the
ConfigMap. This is how configuration works in Kubernetes -- you never
hardcode environment-specific values in the container image.

The result is a Deployment, Service, ConfigMap, and Route.

### Alternative: Local build + push

If you need to push to an external registry (e.g. Quay), build locally instead:

```bash
make build IMAGE_NAME=calculus-agent IMAGE_TAG=v1
podman push calculus-agent:v1 quay.io/your-org/calculus-agent:v1
```

!!! warning "Architecture mismatch"
    `make build` passes `--platform linux/amd64` automatically. If you build
    with raw `podman build` on an Apple Silicon Mac, you must include that flag
    yourself or the image will be ARM64, which will not run on x86_64 OpenShift
    nodes.

## Verify the deployment

Run through these checks to confirm everything is working.

```bash
# 1. Check pod status — you want Running with 1/1 ready
oc get pods -n calculus-agent --context="$CTX" -l app.kubernetes.io/instance=calculus-agent

# 2. Watch logs for startup messages
oc logs deployment/calculus-agent -n calculus-agent --context="$CTX" --tail=15

# 3. Get the external route URL
ROUTE=$(oc get route calculus-agent -n calculus-agent --context="$CTX" -o jsonpath='{.spec.host}')

# 4. Health check
curl -sk "https://$ROUTE/healthz"
# Expected: {"status":"ok"}

# 5. Agent info — confirms identity and model config
curl -sk "https://$ROUTE/v1/agent-info" | python -m json.tool

# 6. Send a real message
curl -sk "https://$ROUTE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is 2+2?"}]}'
```

If step 6 returns a JSON response with the model's answer, your agent is live.

If you enabled observability features (see below), add these checks:

```bash
# 7. Prometheus metrics (if metrics enabled)
curl -sk "https://$ROUTE/metrics"
# Expected: Prometheus text format with agent_requests_total, etc.

# 8. Trace collection (if traces enabled)
curl -sk "https://$ROUTE/v1/traces" | python -m json.tool
# Expected: empty JSON array []
```

## When things go wrong

These are the most common issues and how to fix them.

**ImagePullBackOff** -- Kubernetes cannot pull the container image. The image
repository path is usually wrong. Re-run `fips-agents deploy` (it resolves the
ImageStream automatically) or check the path manually with
`oc get is -n calculus-agent --context="$CTX"` and `helm upgrade`.

**CrashLoopBackOff** -- the container starts and immediately crashes. Check
logs with `oc logs deployment/calculus-agent -n calculus-agent --context="$CTX"`. Common causes:
a missing Python dependency, a syntax error in `agent.yaml`, or a
`PermissionError` on source files (see the warning below).

!!! warning "File permissions in containers"
    The UBI base image runs as a non-root user (UID 1001). If source files
    were copied into the image with owner-only permissions (600), the container
    process cannot read them. The Containerfile includes a `chmod` step to fix
    this, but if you have modified the Containerfile, verify that the
    permission fix is still in place.

**Route returns 503** -- the pod is not ready yet. Wait for the rollout to
finish: `oc rollout status deployment/calculus-agent -n calculus-agent --context="$CTX"`. If the
rollout is stuck, check pod logs.

**Model returns errors** -- if the health check passes but chat completions
fail, the issue is usually the model endpoint. Verify the configured endpoint
from inside the pod:

```bash
oc exec deployment/calculus-agent -n calculus-agent --context="$CTX" -- \
  env | grep MODEL_ENDPOINT
```

Then check that the endpoint is reachable from the pod:

```bash
oc exec deployment/calculus-agent -n calculus-agent --context="$CTX" -- \
  curl -sk "$(<the-endpoint-from-above>)/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**Old image after rebuild** -- OpenShift caches images. After building a new
version, restart the deployment to pick it up:
`oc rollout restart deployment/calculus-agent -n calculus-agent --context="$CTX"`.

## Redeploying after changes

The development cycle for deployed agents is: edit code, rebuild the image,
restart the deployment. You can re-run `fips-agents deploy` for a full
rebuild-and-deploy, or use the manual commands for faster iteration when you
only need to rebuild:

```bash
# 1. Rebuild the image in the cluster
oc start-build calculus-agent --from-dir=. --follow -n calculus-agent --context="$CTX"

# 2. Restart the deployment to pick up the new image
oc rollout restart deployment/calculus-agent -n calculus-agent --context="$CTX"

# 3. Wait for the new pod to become ready
oc rollout status deployment/calculus-agent -n calculus-agent --context="$CTX"
```

The Makefile provides a shortcut that wraps these steps:

```bash
make redeploy PROJECT=calculus-agent
```

!!! tip "Updating configuration without rebuilding"
    If you only need to change environment variables (model endpoint, log level,
    etc.), you do not need to rebuild the image. Re-run `fips-agents deploy`
    with updated `--set config.*` values -- it skips the build when the source
    hasn't changed. Or use `helm upgrade` directly:

    ```bash
    helm upgrade calculus-agent chart/ \
      --set config.MODEL_ENDPOINT=http://new-endpoint.svc.cluster.local/v1 \
      --reuse-values \
      -n calculus-agent --kube-context="$CTX"
    ```

### Optional: Enable observability features

The agent server supports session persistence,
trace collection, and Prometheus metrics. All three are configured under the
`server:` section of `agent.yaml`:

```yaml
server:
  host: ${HOST:-0.0.0.0}
  port: ${PORT:-8080}
  storage:
    backend: sqlite
  sessions:
    enabled: true
  traces:
    enabled: true
  metrics:
    enabled: true
```

To enable these in a deployed agent, re-run `fips-agents deploy` with the
extra config flags:

```bash
fips-agents deploy --context="$CTX" -n calculus-agent \
  --set config.MODEL_ENDPOINT=$MODEL_ENDPOINT \
  --set config.MODEL_NAME=$MODEL_NAME \
  --set config.OPENAI_API_KEY=not-required \
  --set config.STORAGE_BACKEND=sqlite \
  --set config.SESSIONS_ENABLED=true \
  --set config.TRACES_ENABLED=true \
  --set config.METRICS_ENABLED=true
```

Or apply just the observability flags with `helm upgrade --reuse-values`:

```bash
helm upgrade calculus-agent chart/ \
  --set config.STORAGE_BACKEND=sqlite \
  --set config.SESSIONS_ENABLED=true \
  --set config.TRACES_ENABLED=true \
  --set config.METRICS_ENABLED=true \
  --reuse-values \
  -n calculus-agent --kube-context="$CTX"
```

!!! note "Prometheus metrics dependency"
    The `/metrics` endpoint requires the `prometheus_client` library. Add the
    `[metrics]` extra to your `pyproject.toml` dependencies:

        fipsagents[metrics]

    Without this extra, the metrics endpoint will not be available.

For production observability (OTEL export, distributed tracing, PGVector-backed
storage), see [Module 8](08-secrets-and-production.md). The
[agent.yaml Reference](reference/agent-yaml.md) documents all `server:` options.

## What's next

Your agent is running in OpenShift and responding to requests. In
[Module 3](03-build-mcp-server.md), you'll build an MCP server that provides
real calculus tools for the agent to use.
