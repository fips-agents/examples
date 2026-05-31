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

The authoritative reference is the
[official Red Hat guide](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/govern_llm_access_with_models-as-a-service/deploy-and-manage-models-as-a-service_maas).
The steps below inline the key operations with troubleshooting context that
the official guide does not cover.

!!! note "Red Hat account required"
    The official guide requires a Red Hat login. If you don't have one,
    create a free account at [access.redhat.com](https://access.redhat.com).

### Step 1: Install the Limitador operator

Subscribe from OperatorHub on the `stable` channel from the
`redhat-operators` catalog. The operator installs into `openshift-operators`.

```bash
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: limitador-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: limitador-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

Wait for the CSV to succeed:

```bash
oc get csv -n openshift-operators -l operators.coreos.com/limitador-operator.openshift-operators
```

### Step 2: Install or upgrade the Authorino operator

!!! warning "Upgrading from RHOAI 3.3"
    If you have Authorino v1.1.3 on the `tech-preview-v1` channel, it is
    too old for Connectivity Link. Delete the old Subscription and CSV
    first, then install fresh on `stable`. This can briefly disrupt cluster
    auth.

    ```bash
    oc delete subscription authorino-operator -n openshift-operators
    oc delete csv -l operators.coreos.com/authorino-operator.openshift-operators \
      -n openshift-operators
    ```

For a fresh install, subscribe on the `stable` channel (v1.3.0+):

```bash
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: authorino-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: authorino-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

The operator installs into `openshift-operators`, but the Authorino CR will
live in `kuadrant-system` (managed by RHCL in Step 4).

### Step 3: Install the Red Hat Connectivity Link (RHCL) operator

Subscribe on the `stable` channel (v1.3.3). This brings Kuadrant
capabilities to the cluster.

```bash
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: connectivity-link-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: connectivity-link-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

### Step 4: Create the Kuadrant CR

Installing the RHCL operator is not enough -- you must also create the
Kuadrant custom resource:

```bash
oc create namespace kuadrant-system --dry-run=client -o yaml | oc apply -f -

oc apply -f - <<EOF
apiVersion: kuadrant.io/v1beta1
kind: Kuadrant
metadata:
  name: kuadrant
  namespace: kuadrant-system
spec: {}
EOF
```

Wait for Ready:

```bash
oc get kuadrant kuadrant -n kuadrant-system \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# Should print True
```

!!! warning "Kuadrant stuck in MissingDependency"
    Kuadrant checks for Limitador during initialization and caches a
    `MissingDependency` status permanently if Limitador was not ready in
    time. If the Kuadrant CR stays in `MissingDependency` after Limitador
    is healthy, restart the Kuadrant operator pod:

    ```bash
    oc delete pod -l app.kubernetes.io/name=kuadrant-operator \
      -n kuadrant-system
    ```

    Then re-check readiness.

### Step 5: Deploy PostgreSQL and create the database secret

MaaS needs PostgreSQL for API key management. Deploy PostgreSQL however your
cluster standards require, then create the connection secret in the
`redhat-ods-applications` namespace:

```bash
oc create secret generic maas-db-config \
  -n redhat-ods-applications \
  --from-literal=host=<postgres-host> \
  --from-literal=port=5432 \
  --from-literal=dbname=maas \
  --from-literal=user=maas \
  --from-literal=password=<password>
```

!!! tip "Database timing"
    If the `maas-api` pod starts before the database is ready, the schema
    will not initialize. Restart it after the database is available:

    ```bash
    oc rollout restart deployment/maas-api -n redhat-ods-applications
    ```

### Step 6: Create the MaaS gateway

Create a Gateway in the `openshift-ingress` namespace with ClusterIP service
type and passthrough Routes for external access.

```yaml
# maas-gateway.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: maas-default-gateway
  namespace: openshift-ingress
  annotations:
    opendatahub.io/managed: "false"
    security.opendatahub.io/authorino-tls-bootstrap: "true"
spec:
  gatewayClassName: data-science-gateway-class  # (1)
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - name: maas-default-gateway-cert
      allowedRoutes:
        namespaces:
          from: All
```

1. Find your GatewayClass: `oc get gatewayclasses`

Then create two passthrough Routes for external access:

```yaml
# maas-routes.yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: maas-gateway
  namespace: openshift-ingress
spec:
  host: maas.apps.<cluster-domain>
  to:
    kind: Service
    name: maas-default-gateway-data-science-gateway-class
  port:
    targetPort: https
  tls:
    termination: passthrough
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: maas-inference-gateway
  namespace: openshift-ingress
spec:
  host: inference.maas.apps.<cluster-domain>
  to:
    kind: Service
    name: maas-default-gateway-data-science-gateway-class
  port:
    targetPort: https
  tls:
    termination: passthrough
```

```bash
oc apply -f maas-gateway.yaml
oc apply -f maas-routes.yaml
```

!!! warning "Do not put hostnames on Gateway listeners"
    The gateway service uses ClusterIP with passthrough Routes for external
    access. Placing hostnames directly on listeners can cause DNS record
    hijacking -- the gateway takes over records from OpenShift's default
    router.

    Also note: `*.maas.apps.<domain>` (wildcard) matches subdomains like
    `inference.maas.apps.<domain>` but NOT the bare `maas.apps.<domain>`.
    If you need both, create explicit Routes for each.

### Step 7: Configure TLS for Authorino

Three steps are required -- setting `certSecretRef` alone is not enough.

**7a.** Annotate the Authorino service for a serving certificate:

```bash
oc annotate service authorino-authorino-authorization \
  service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert \
  -n kuadrant-system
```

**7b.** Patch the Authorino CR with TLS enabled:

```bash
oc patch authorino authorino -n kuadrant-system --type merge -p '{
  "spec": {
    "listener": {
      "tls": {
        "enabled": true,
        "certSecretRef": {
          "name": "authorino-server-cert"
        }
      }
    }
  }
}'
```

!!! warning "`enabled: true` is required"
    Setting only `certSecretRef` looks correct but fails silently --
    gateway-to-Authorino communication breaks and models will not appear
    in Gen AI Studio. You must set `enabled: true` alongside
    `certSecretRef`.

**7c.** Add CA bundle environment variables to the Authorino deployment:

```bash
oc set env deployment/authorino-authorino-authorization \
  SSL_CERT_FILE=/etc/ssl/certs/openshift-service-ca/service-ca-bundle.crt \
  REQUESTS_CA_BUNDLE=/etc/ssl/certs/openshift-service-ca/service-ca-bundle.crt \
  -n kuadrant-system
```

### Step 8: Enable User Workload Monitoring

```bash
oc apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
data:
  config.yaml: |
    enableUserWorkload: true
EOF
```

Without User Workload Monitoring, MaaS reports a Degraded status.

### Step 9: Enable MaaS in the DataScienceCluster

```bash
oc patch dsc default-dsc --type merge -p '{
  "spec": {
    "components": {
      "kserve": {
        "modelsAsService": {
          "managementState": "Managed"
        }
      }
    }
  }
}'
```

### Step 10: Enable dashboard feature flags

```bash
oc patch odhdashboardconfig odh-dashboard-config \
  -n redhat-ods-applications --type merge -p '{
  "spec": {
    "dashboardConfig": {
      "modelAsService": true,
      "genAiStudio": true,
      "maasAuthPolicies": true
    }
  }
}'
```

### Step 11: Verify the deployment

```bash
oc get tenants.maas.opendatahub.io default-tenant \
  -n models-as-a-service
```

READY should be True. If it is not, work backwards through Kuadrant CR
status, Authorino TLS configuration, and User Workload Monitoring.

!!! warning "Additional troubleshooting"
    **AI Hub model catalog requires Model Registry.** To see the model
    catalog under AI Hub in the dashboard, enable `modelregistry` and
    `llamastackoperator` in the DSC:

    ```bash
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
    creates HTTPRoutes in model namespaces. The
    `allowedRoutes.namespaces.from: All` in the gateway listener handles
    this -- if you see `NotAllowedByListeners`, check your gateway config.

    **GPU node taints.** If your GPU nodes have a
    `nvidia.com/gpu:NoSchedule` taint, the `LLMInferenceService`
    controller does not propagate tolerations from hardware profiles.
    Either remove the taint from GPU nodes or patch the Deployment
    directly after model deployment.

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
