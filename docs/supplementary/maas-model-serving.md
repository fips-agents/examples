# Models as a Service

Models as a Service (MaaS) adds a governance layer to model serving. Instead
of each team managing their own vLLM instance (what you did in Path A of the
[Serve an LLM](../guides/serve-an-llm.md) guide), a platform team publishes
models through a managed gateway with subscription-based quotas, API key
authentication, and usage tracking. Developers get self-service API keys and
hit a single OpenAI-compatible endpoint.

This module walks through deploying MaaS on your cluster, publishing a model,
understanding the resources MaaS creates, building governance resources by
hand, and rewiring the calculus-agent to consume the model through the
governed gateway.

!!! info "Prerequisites"
    - RHOAI 3.4 on OpenShift 4.19.9+
    - Modules 0--2 complete (agent scaffolded, configured, deployed)
    - [Serve an LLM](../guides/serve-an-llm.md) Path A completed (so you
      have direct vLLM to compare against)
    - `cluster-admin` access
    - A GPU node (same requirements as Path A)

## What you will build

```
Current (Path A):

  Agent --> vLLM InferenceService (direct, no auth)

After (MaaS):

  Agent --> MaaS Gateway --> llm-d (EPP) --> vLLM
               |
               +-- MaaSSubscription (token quotas)
               +-- MaaSAuthPolicy (group access)
               +-- API key auth (sk-oai-*)
```

The agent code does not change. Only the endpoint URL and the addition of an
API key differ.

## Part 1: Deploy MaaS on your cluster

MaaS requires several platform components: Red Hat Connectivity Link
(Kuadrant, Authorino, Limitador), a PostgreSQL database for API key
management, an API gateway with TLS, and dashboard configuration.

Follow the official Red Hat guide to deploy MaaS:

**[Deploy and manage Models-as-a-Service](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/govern_llm_access_with_models-as-a-service/deploy-and-manage-models-as-a-service_maas#maas-prerequisites_maas-deploy)**

!!! note "Red Hat account required"
    The official guide requires a Red Hat login. If you don't have one,
    create a free account at [access.redhat.com](https://access.redhat.com).

Work through the prerequisites section and the initial configuration steps.
When you are done, verify the deployment:

```bash
oc get tenants.maas.opendatahub.io default-tenant \
  -n models-as-a-service
# READY should be True
```

!!! warning "Gotchas we found during testing"
    These issues are not covered in the official guide but came up during
    our validation on fresh clusters:

    **AI Hub model catalog requires Model Registry.** To see the model
    catalog under AI Hub in the dashboard, enable `modelregistry` in the
    DSC and `llamastackoperator` for GenAI Studio:

    ```
    oc patch dsc default-dsc --type merge -p '{
      "spec": {
        "components": {
          "llamastackoperator": {"managementState": "Managed"},
          "modelregistry": {
            "managementState": "Managed",
            "registriesNamespace": "rhoai-model-registries"
          }
        }
      }
    }'
    ```

    **Gateway must allow cross-namespace routes.** The MaaS controller
    creates HTTPRoutes in model namespaces. Add
    `allowedRoutes.namespaces.from: All` to the gateway listener, or model
    deployments fail with `NotAllowedByListeners`.

    **Restart maas-api after creating the database.** If PostgreSQL is
    deployed after the `maas-api` pod starts, the database schema won't
    be initialized. Run
    `oc rollout restart deployment/maas-api -n redhat-ods-applications`
    to trigger the migration.

    **GPU node taints.** If your GPU nodes have a `nvidia.com/gpu:NoSchedule`
    taint, the `LLMInferenceService` controller does not propagate
    tolerations from hardware profiles. Either remove the taint from GPU
    nodes or patch the Deployment directly after model deployment.

    **Authorino upgrade from RHOAI 3.3.** If upgrading from 3.3, the
    Authorino operator (v1.1.3, `tech-preview-v1` channel) is too old for
    Connectivity Link. Delete the old Subscription and CSV, then recreate
    on the `stable` channel. This can briefly disrupt cluster auth.

## Part 2: Deploy a model from the AI Hub catalog

With MaaS deployed, open the RHOAI dashboard and navigate to **AI Hub >
Catalog**. Find `gpt-oss-20b` (or search for it), click the model card, then
click **Deploy**.

The deployment wizard walks you through:

1. **Model details** -- the catalog pre-fills the model URI and format.
   Select **Generative AI model**. Leave **Use legacy deployment method**
   unchecked.
2. **Model deployment** -- select your GPU hardware profile, choose
   **Distributed inference with llm-d** as the deployment resource, set
   replicas to 1.
3. **Advanced settings** -- select **Publish as MaaS**. This registers the
   model with the MaaS gateway.
4. **Review** and deploy.

Wait for the model to become ready (the first deploy downloads model weights
as an OCI image, which can take 10--15 minutes):

```bash
oc get llminferenceservice -n gpt-oss-model
# READY should be True
```

Verify the model was published to MaaS:

```bash
oc get maasmodelref -n gpt-oss-model
# PHASE should be Ready
```

## Part 3: Understand what MaaS built

The catalog and MaaS controller created several resources. Inspect them to
understand what's running.

### The LLMInferenceService

This is the core resource -- it replaces the standalone `InferenceService`
from Path A:

```bash
oc get llminferenceservice -n gpt-oss-model -o yaml
```

Key sections:

**`spec.model`** -- the model identity and source:

```yaml
spec:
  model:
    name: RedHatAI/gpt-oss-20b
    uri: hf://RedHatAI/gpt-oss-20b   # hf:// scheme, not https://
```

The `hf://` URI tells the storage initializer to pull from Hugging Face. The
catalog may use an OCI image URI instead (`oci://registry.redhat.io/...`),
which packages the weights as a container image -- faster and more
reproducible than a git-lfs download.

**`spec.router`** -- connects this model to the MaaS gateway:

```yaml
spec:
  router:
    route: {}
    gateway:
      refs:
        - name: maas-default-gateway
          namespace: openshift-ingress
```

The MaaS controller reads this and auto-creates an `HTTPRoute` that maps
`/<namespace>/<name>/v1/*` on the gateway to this model's backend pods.

**`spec.template`** -- the pod template, similar to a Deployment:

```yaml
spec:
  template:
    containers:
      - name: main
        image: registry.redhat.io/rhaiis/vllm-cuda-rhel9:3
        args:
          - --dtype
          - bfloat16
          - --enforce-eager
          - --enable-auto-tool-choice
          - --tool-call-parser
          - openai
          # ... same vLLM args as Path A's ServingRuntime
```

These are the same vLLM arguments you used in Path A. The model runs on the
same inference engine -- MaaS is a governance layer, not a different runtime.

### The llm-d components

Look at the running pods:

```bash
oc get pods -n gpt-oss-model
```

You'll see two deployments:

- **`<name>-kserve`** -- the vLLM model server (your GPU workload)
- **`<name>-kserve-router-scheduler`** -- the llm-d Endpoint Picker (EPP)

The EPP is what [Module 11](../11-scaling-with-llm-d.md) described
conceptually. With one replica it's a pass-through, but with multiple
replicas it routes requests based on KV-cache utilization, queue depth, and
prefix cache hit rate. You're running llm-d in production -- the catalog
deployed it for you.

### The MaaSModelRef

"Publish as MaaS" created this resource:

```bash
oc get maasmodelref -n gpt-oss-model -o yaml
```

It references the `LLMInferenceService` and the gateway, making the model
visible to the MaaS subscription and auth policy system. Without it, the
model serves inference but isn't governed.

## Part 4: Build a subscription and auth policy by hand

MaaS uses two custom resources to control who can access what:

- **`MaaSSubscription`** -- grants groups quota for models with token limits
- **`MaaSAuthPolicy`** -- authorizes groups to access model endpoints
  through the API gateway

Both are required. A subscription without an auth policy results in 403
errors.

### Create an OpenShift group

MaaS resolves access by group membership. Create a group and add yourself:

```bash
oc adm groups new calculus-users <your-username>
```

!!! note "Users with colons in their name"
    If your username contains a colon (e.g. `kube:admin`), encode it:
    `oc adm groups new calculus-users "b64:$(echo -n 'kube:admin' | base64)"`
    -- and also add the user directly to the subscription's `owner.users`
    list (see below).

### Build the MaaSSubscription

Start with the required fields and build up:

```yaml
# maas-subscription.yaml
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSSubscription
metadata:
  name: calculus-dev
  namespace: models-as-a-service
spec:
  # Priority determines which subscription is used when a user belongs
  # to multiple groups. Higher number = higher priority.
  priority: 0

  # Who owns this subscription -- groups and/or individual users
  owner:
    groups:
      - name: calculus-users
    # users:             # optional: add individual users directly
    #   - "kube:admin"   # useful when group resolution has issues

  # Which models this subscription grants quota for
  modelRefs:
    - name: <maasmodelref-name>       # from: oc get maasmodelref -n gpt-oss-model
      namespace: gpt-oss-model
      tokenRateLimits:
        - limit: 50000                # 50k tokens
          window: 1h                  # per hour
```

Fill in the `<maasmodelref-name>` from your cluster:

```bash
oc get maasmodelref -n gpt-oss-model -o custom-columns='NAME:.metadata.name'
```

Apply:

```bash
oc apply -f maas-subscription.yaml
oc get maassubscriptions -n models-as-a-service
# Phase should be Active
```

### Build the MaaSAuthPolicy

The auth policy uses the same group and model references:

```yaml
# maas-auth-policy.yaml
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSAuthPolicy
metadata:
  name: calculus-dev-access
  namespace: models-as-a-service
spec:
  # Who can access -- groups and/or individual users
  subjects:
    groups:
      - name: calculus-users
    # users:
    #   - "kube:admin"

  # Which model endpoints this policy authorizes
  modelRefs:
    - name: <maasmodelref-name>
      namespace: gpt-oss-model
```

Apply:

```bash
oc apply -f maas-auth-policy.yaml
oc get maasauthpolicies -n models-as-a-service
# Phase should be Active
```

!!! tip "Dashboard alternative"
    You can also create both resources through the RHOAI dashboard:
    **Settings > Subscriptions > Create subscription**. Check **Create a
    matching authorization policy** to create both in one step.

## Part 5: Get an API key and test

### Generate an API key

Through the dashboard: **Gen AI studio > API keys > Create API key**. Select
the `calculus-dev` subscription and save the generated `sk-oai-*` key.

Or via the MaaS API:

```bash
MAAS_URL="https://<maas-gateway-route-hostname>"
OCP_TOKEN=$(oc whoami -t)

API_KEY=$(curl -sk "${MAAS_URL}/maas-api/v1/api-keys" \
  -H "Authorization: Bearer ${OCP_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name": "calculus-agent-key", "subscription": "calculus-dev"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])")

echo "API key: ${API_KEY}"
```

Replace `<maas-gateway-route-hostname>` with your gateway's external
hostname. Find it in the OpenShift console under **Networking > Routes** in
the `openshift-ingress` namespace, or from the RHOAI dashboard's AI asset
endpoints page.

!!! warning "Save the key"
    The full API key is shown only at creation time. Store it securely.

### Test inference

```bash
MODEL_NAME=$(oc get maasmodelref -n gpt-oss-model \
  -o jsonpath='{.items[0].metadata.name}')

curl -sk "${MAAS_URL}/gpt-oss-model/${MODEL_NAME}/v1/chat/completions" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${MODEL_NAME}\",
    \"messages\": [{\"role\": \"user\", \"content\": \"What is the derivative of x^3 + 2x?\"}],
    \"max_tokens\": 200
  }" | python3 -m json.tool
```

You should see a response with `content` (the answer) and
`reasoning` (the chain-of-thought) -- the same format as Path A.

## Part 6: Wire the calculus-agent to MaaS

The agent code is identical -- only environment variables change:

| Variable | Path A (direct vLLM) | MaaS |
|----------|---------------------|------|
| `MODEL_ENDPOINT` | `http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local:8000/v1` | `https://<maas-gateway>/gpt-oss-model/<model-name>/v1` |
| `MODEL_NAME` | `RedHatAI/gpt-oss-20b` | `<maasmodelref-name>` |
| `OPENAI_API_KEY` | (not set or dummy) | `<your-maas-api-key>` |

Update the agent's ConfigMap and create a Secret for the API key:

```bash
oc patch configmap calculus-agent-config \
  -n calculus-agent \
  --type merge -p "{
    \"data\": {
      \"MODEL_ENDPOINT\": \"${MAAS_URL}/gpt-oss-model/${MODEL_NAME}/v1\",
      \"MODEL_NAME\": \"${MODEL_NAME}\"
    }
  }"

oc create secret generic maas-api-key \
  --from-literal=OPENAI_API_KEY="${API_KEY}" \
  -n calculus-agent
```

Reference the Secret in your Helm values or Deployment so the agent pod
mounts `OPENAI_API_KEY` as an environment variable, then redeploy:

```bash
cd calculus-agent
make deploy
```

Test the agent end-to-end:

```bash
curl -s http://calculus-agent.calculus-agent.svc.cluster.local:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is the derivative of x^3?"}]
  }' | python3 -m json.tool
```

!!! note "Same model, same API"
    The agent code does not change at all. MaaS is an infrastructure concern
    -- the OpenAI-compatible API is preserved end-to-end. The agent points
    at a different URL and adds an API key.

## Part 7: Monitor usage

MaaS tracks token consumption, request counts, and rate-limit violations
through Prometheus metrics. Enable telemetry in the Tenant CR:

```bash
oc patch tenants.maas.opendatahub.io default-tenant \
  -n models-as-a-service --type merge -p '{
  "spec": {
    "telemetry": {
      "enabled": true,
      "metrics": {
        "captureOrganization": true,
        "captureModelUsage": true
      }
    }
  }
}'
```

View usage in the RHOAI dashboard under **Observe & monitor > Dashboard >
Usage** tab, or query Prometheus directly:

```promql
sum by (subscription, model) (
  rate(authorized_hits[1h])
)
```

!!! warning "Observability dashboard is Tech Preview"
    The MaaS Usage tab in the RHOAI dashboard is a Technology Preview
    feature in 3.4. The underlying Prometheus metrics (`authorized_hits`,
    `authorized_calls`, `limited_calls`) are stable.

## What changed

| Aspect | Path A (direct vLLM) | MaaS |
|--------|---------------------|------|
| Model runtime | KServe `InferenceService` | `LLMInferenceService` (llm-d + vLLM) |
| Endpoint | In-cluster Service URL | MaaS gateway with auth |
| Authentication | None (in-cluster trust) | API key (`sk-oai-*`) via Authorino |
| Quota management | None | `MaaSSubscription` with token limits per group |
| Access control | None | `MaaSAuthPolicy` per group per model |
| Cost visibility | None | Token consumption metrics and CSV export |
| Scaling | Manual replica count | llm-d EPP routes across replicas by KV-cache load |
| Multi-model | One InferenceService per model | One gateway, many models |
| Agent code changes | -- | None (env vars only) |

## What's next

- [MCP Gateway](mcp-gateway.md) -- centralize access to MCP servers through a
  governed gateway, the same way MaaS centralizes model access
- [Where to Go Next](../where-next.md) -- the full picture of what comes after
  this tutorial
