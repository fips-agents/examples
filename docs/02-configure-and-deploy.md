# Module 2: Configure and Deploy to OpenShift

Now that you understand the project layout, it is time to configure the agent
for a real LLM endpoint and deploy it to OpenShift. By the end of this module
your agent will be running in a pod, reachable over HTTPS, and answering
questions using a model served by vLLM or LlamaStack.

## Set your model endpoint

Open `agent.yaml` and find the `model:` section. This is where you tell the
agent which LLM to call. Every value supports `${VAR:-default}` substitution,
so the same file works for local development (use the defaults) and production
(inject env vars via ConfigMap).

```yaml
model:
  endpoint: ${MODEL_ENDPOINT:-http://vllm-predictor.model-ns.svc.cluster.local/v1}
  name: ${MODEL_NAME:-/mnt/models}
  temperature: 0.7
  max_tokens: 4096
```

The `endpoint` is an OpenAI-compatible `/v1` URL. The `name` is whatever the
inference server expects as the model identifier -- for vLLM this is typically
the Hugging Face model ID or `/mnt/models` if the model is loaded from a local
path.

!!! tip "Finding your model endpoint"
    If your model is deployed via OpenShift AI (RHOAI), the internal service URL
    follows the pattern:

        http://<inference-service-name>-predictor.<namespace>.svc.cluster.local/v1

    List all InferenceServices across namespaces to find yours:

        oc get inferenceservice -A

!!! info "Why OPENAI_API_KEY?"
    The OpenAI Python SDK requires an API key even when calling unauthenticated
    endpoints like vLLM. Set `OPENAI_API_KEY` to any non-empty string (e.g.
    `not-required`) to satisfy the SDK. The agent's ConfigMap handles this for
    you in the Helm deploy step below.

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
stream path (e.g. `image-registry.openshift-image-registry.svc:5000/my-namespace/calculus-agent`).

**`config.*`** -- every key under `config:` becomes an environment variable in
the ConfigMap. These are substituted into `agent.yaml` at runtime. For example,
setting `config.MODEL_ENDPOINT` overrides the `${MODEL_ENDPOINT}` placeholder.

**`route.enabled`** -- when `true`, the chart creates an OpenShift Route that
gives your agent an external HTTPS URL. When `false`, the agent is only
reachable inside the cluster via its Service.

**`resources`** -- CPU and memory requests/limits. The defaults (100m CPU,
256Mi memory) are reasonable because the agent is I/O-bound: it spends most
of its time waiting for LLM responses over the network.

## Build the container image

You need a container image before you can deploy. There are two approaches.

### Option A: OpenShift BuildConfig (recommended)

A BuildConfig builds your image directly in the cluster's internal registry.
No need to push images to an external registry, and the build runs on x86_64
regardless of your laptop's architecture.

```bash
# Create a binary BuildConfig that accepts source uploads
oc new-build --binary --name=calculus-agent --strategy=docker -n my-namespace

# Tell it to use Containerfile instead of Dockerfile
oc patch bc/calculus-agent --type=json \
  -p '[{"op":"replace","path":"/spec/strategy/dockerStrategy/dockerfilePath","value":"Containerfile"}]' \
  -n my-namespace

# Upload your source and start the build
oc start-build calculus-agent --from-dir=. --follow -n my-namespace
```

!!! info "What is a BuildConfig?"
    A BuildConfig is an OpenShift resource that tells the platform how to build
    a container image. With `--binary`, it accepts source code uploaded from
    your local machine and builds the image server-side. The resulting image is
    pushed to the cluster's internal registry automatically -- no external
    registry credentials needed.

The `--follow` flag streams build logs to your terminal. When the build
completes you will see a line like `Push successful` followed by the internal
image reference.

### Option B: Local build + push

If you prefer to build locally (or need to push to an external registry like
Quay), use the Makefile target:

```bash
make build IMAGE_NAME=calculus-agent IMAGE_TAG=v1
podman push calculus-agent:v1 quay.io/your-org/calculus-agent:v1
```

!!! warning "Architecture mismatch"
    `make build` passes `--platform linux/amd64` automatically. If you build
    with raw `podman build` on an Apple Silicon Mac, you must include that flag
    yourself or the image will be ARM64, which will not run on x86_64 OpenShift
    nodes.

## Deploy with Helm

With the image built, deploy the agent:

```bash
# Get the internal registry path for the image we just built
IMAGE=$(oc get is calculus-agent -n my-namespace -o jsonpath='{.status.dockerImageRepository}')

# Deploy the chart
helm install calculus-agent chart/ \
  --set image.repository=$IMAGE \
  --set image.tag=latest \
  --set image.pullPolicy=Always \
  --set config.MODEL_ENDPOINT=http://vllm-predictor.model-ns.svc.cluster.local/v1 \
  --set config.MODEL_NAME=/mnt/models \
  --set config.OPENAI_API_KEY=not-required \
  --set route.enabled=true \
  -n my-namespace
```

Here is what each `--set` does:

- **`image.repository`** -- points at the image stream in the internal
  registry. The `oc get is` command retrieves the full path.
- **`image.tag`** -- `latest` tracks the most recent build. Pin to a specific
  tag for production.
- **`image.pullPolicy=Always`** -- forces Kubernetes to pull the image on every
  pod restart, so you always get the latest build.
- **`config.MODEL_ENDPOINT`** -- the `/v1` URL of your vLLM or LlamaStack
  inference endpoint.
- **`config.MODEL_NAME`** -- the model identifier your endpoint expects.
- **`config.OPENAI_API_KEY`** -- satisfies the SDK requirement. Set to a real
  key only if your endpoint requires authentication.
- **`route.enabled=true`** -- creates an OpenShift Route so you can reach the
  agent from outside the cluster.

!!! info "What is an ImageStream?"
    An ImageStream is an OpenShift abstraction that tracks container images in
    the internal registry. When you build with a BuildConfig, the output image
    is tagged in an ImageStream. `oc get is` shows you the registry path that
    Kubernetes needs to pull the image.

## Verify the deployment

Run through these checks to confirm everything is working.

```bash
# 1. Check pod status — you want Running with 1/1 ready
oc get pods -n my-namespace -l app.kubernetes.io/instance=calculus-agent

# 2. Watch logs for startup messages
oc logs deployment/calculus-agent -n my-namespace --tail=15

# 3. Get the external route URL
ROUTE=$(oc get route calculus-agent -n my-namespace -o jsonpath='{.spec.host}')

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

## When things go wrong

These are the most common issues and how to fix them.

**ImagePullBackOff** -- Kubernetes cannot pull the container image. The image
repository path is usually wrong. Run `oc get is -n my-namespace` to find
the correct internal registry path, then `helm upgrade` with the corrected
`image.repository` value.

**CrashLoopBackOff** -- the container starts and immediately crashes. Check
logs with `oc logs deployment/calculus-agent -n my-namespace`. Common causes:
a missing Python dependency, a syntax error in `agent.yaml`, or a
`PermissionError` on source files (see the warning below).

!!! warning "File permissions in containers"
    The UBI base image runs as a non-root user (UID 1001). If source files
    were copied into the image with owner-only permissions (600), the container
    process cannot read them. The Containerfile includes a `chmod` step to fix
    this, but if you have modified the Containerfile, verify that the
    permission fix is still in place.

**Route returns 503** -- the pod is not ready yet. Wait for the rollout to
finish: `oc rollout status deployment/calculus-agent -n my-namespace`. If the
rollout is stuck, check pod logs.

**Model returns errors** -- if the health check passes but chat completions
fail, the issue is usually the model endpoint. Verify the endpoint is reachable
from inside the cluster:

```bash
oc exec deployment/calculus-agent -n my-namespace -- \
  curl -s http://vllm-predictor.model-ns.svc.cluster.local/v1/models
```

**Old image after rebuild** -- OpenShift caches images. After building a new
version, restart the deployment to pick it up:
`oc rollout restart deployment/calculus-agent -n my-namespace`.

## Redeploying after changes

The development cycle for deployed agents is: edit code, rebuild the image,
restart the deployment. Here is the sequence:

```bash
# 1. Rebuild the image in the cluster
oc start-build calculus-agent --from-dir=. --follow -n my-namespace

# 2. Restart the deployment to pick up the new image
oc rollout restart deployment/calculus-agent -n my-namespace

# 3. Wait for the new pod to become ready
oc rollout status deployment/calculus-agent -n my-namespace
```

The Makefile provides a shortcut that wraps these steps:

```bash
make redeploy PROJECT=my-namespace
```

!!! tip "Updating configuration without rebuilding"
    If you only need to change environment variables (model endpoint, log level,
    etc.), you do not need to rebuild the image. Run `helm upgrade` with the new
    `--set config.*` values. The ConfigMap checksum annotation in the Deployment
    template automatically triggers a rolling restart when the ConfigMap changes.

    ```bash
    helm upgrade calculus-agent chart/ \
      --set config.MODEL_ENDPOINT=http://new-endpoint.svc.cluster.local/v1 \
      --reuse-values \
      -n my-namespace
    ```

## What's next

Your agent is running in OpenShift and responding to requests. In
[Module 3](03-build-mcp-server.md), you'll build an MCP server that provides
real calculus tools for the agent to use.
