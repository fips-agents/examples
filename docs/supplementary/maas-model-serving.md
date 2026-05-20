# Models as a Service

Models as a Service (MaaS) adds a governance layer to model serving. Instead
of each team managing their own vLLM instance (what you did in Path A of the
[Serve an LLM](../guides/serve-an-llm.md) guide), a platform team publishes
models through a managed gateway with subscription-based quotas, API key
authentication, and usage tracking. Developers get self-service API keys and
hit a single OpenAI-compatible endpoint.

This module walks through enabling MaaS on your cluster, publishing the same
`RedHatAI/gpt-oss-20b` model you served in Path A, creating a subscription,
and rewiring the calculus-agent to consume the model through the governed
gateway.

!!! info "Prerequisites"
    - RHOAI 3.4 on OpenShift 4.19.9+
    - Modules 0--2 complete (agent scaffolded, configured, deployed)
    - [Serve an LLM](../guides/serve-an-llm.md) Path A completed (so you
      have direct vLLM to compare against)
    - `cluster-admin` access

## What you will build

```
Current (Path A):

  Agent --> vLLM InferenceService (direct, no auth)

After (MaaS):

  Agent --> MaaS Gateway --> vLLM (or llm-d)
               |
               +-- Subscription (token quotas)
               +-- AuthPolicy (group access)
               +-- API key auth
```

The agent code does not change. Only the endpoint URL and the addition of an
API key differ.

## Part 1: Install the prerequisite operators

MaaS requires Red Hat Connectivity Link, which in turn requires Limitador and
Authorino v1.3+. If you are upgrading from RHOAI 3.3, the Authorino operator
installed by RHOAI (v1.1.3 on the `tech-preview-v1` channel) is too old --
you must replace it.

### Install Limitador

```bash
oc apply -f - <<'EOF'
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
  installPlanApproval: Automatic
EOF
```

Wait for the CSV to succeed:

```bash
oc get csv -n openshift-operators | grep limitador
```

### Upgrade Authorino (3.3 → 3.4 only)

If your cluster was running RHOAI 3.3, Authorino v1.1.3 is installed on the
`tech-preview-v1` channel. Connectivity Link requires v1.3.0 on the `stable`
channel. An in-place channel switch does not work -- delete and recreate.

```bash
OLD_CSV=$(oc get subscription authorino-operator \
  -n openshift-operators -o jsonpath='{.status.installedCSV}')
oc delete subscription authorino-operator -n openshift-operators
oc delete csv "$OLD_CSV" -n openshift-operators
```

Recreate on the `stable` channel:

```bash
oc apply -f - <<'EOF'
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
  installPlanApproval: Automatic
EOF
```

!!! warning "Temporary auth disruption"
    Upgrading Authorino can briefly disrupt `oc` authentication on the
    cluster. If you see `Unauthorized` errors, wait a minute and retry. If
    the Authorino operator pod enters CrashLoopBackOff, delete it to force
    an immediate restart:
    `oc delete pod -l control-plane=authorino-operator -n openshift-operators`

Wait for v1.3.0:

```bash
oc get csv -n openshift-operators | grep authorino
# authorino-operator.v1.3.0   Succeeded
```

### Install Red Hat Connectivity Link

```bash
oc apply -f - <<'EOF'
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: rhcl-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: rhcl-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
EOF
```

Wait for the CSV:

```bash
oc get csv -n openshift-operators | grep rhcl
# rhcl-operator.v1.3.3   Succeeded
```

### Create the Kuadrant custom resource

Connectivity Link needs a `Kuadrant` CR in the `kuadrant-system` namespace
to activate its control plane:

```bash
oc create namespace kuadrant-system 2>/dev/null || true

oc apply -f - <<'EOF'
apiVersion: kuadrant.io/v1beta1
kind: Kuadrant
metadata:
  name: kuadrant
  namespace: kuadrant-system
EOF
```

Wait for it to become ready:

```bash
oc wait kuadrant kuadrant -n kuadrant-system \
  --for=condition=Ready --timeout=300s
```

## Part 2: Configure MaaS infrastructure

### Deploy PostgreSQL

MaaS needs a PostgreSQL database (v14+) for API key lifecycle management.
OpenShift AI does not provide one -- you deploy your own.

```bash
oc apply -n redhat-ods-applications -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: maas-db
spec:
  replicas: 1
  selector:
    matchLabels:
      app: maas-db
  template:
    metadata:
      labels:
        app: maas-db
    spec:
      containers:
        - name: postgres
          image: registry.redhat.io/rhel9/postgresql-16:latest
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRESQL_USER
              value: maas
            - name: POSTGRESQL_PASSWORD
              value: maas-password
            - name: POSTGRESQL_DATABASE
              value: maas
          volumeMounts:
            - name: data
              mountPath: /var/lib/pgsql/data
      volumes:
        - name: data
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: maas-db
spec:
  selector:
    app: maas-db
  ports:
    - port: 5432
      targetPort: 5432
EOF
```

Create the connection secret:

```bash
oc create secret generic maas-db-config \
  -n redhat-ods-applications \
  --from-literal=DB_CONNECTION_URL='postgresql://maas:maas-password@maas-db.redhat-ods-applications.svc.cluster.local:5432/maas?sslmode=disable'
```

!!! warning "Production databases"
    The `emptyDir` PostgreSQL above is for learning only -- data is lost on
    pod restart. Production deployments should use a persistent database
    with TLS (`sslmode=require`).

### Create the MaaS gateway

```bash
oc apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: maas-default-gateway
  namespace: openshift-ingress
  annotations:
    opendatahub.io/managed: "false"
    security.opendatahub.io/authorino-tls-bootstrap: "true"
spec:
  gatewayClassName: data-science-gateway-class
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      allowedRoutes:
        namespaces:
          from: All
      tls:
        mode: Terminate
        certificateRefs:
          - name: maas-gateway-tls
EOF
```

!!! note "Gateway annotations"
    `opendatahub.io/managed: "false"` lets the MaaS controller manage auth
    policies without interference from the ODH Model Controller.
    `security.opendatahub.io/authorino-tls-bootstrap: "true"` enables TLS
    between the gateway and Authorino.

Verify it becomes Programmed:

```bash
oc wait gateway maas-default-gateway -n openshift-ingress \
  --for=condition=Programmed --timeout=120s
```

The gateway's HTTPS listener references a `maas-gateway-tls` secret. Generate
it by annotating the auto-created gateway Service:

```bash
oc annotate service maas-default-gateway-data-science-gateway-class \
  -n openshift-ingress \
  service.beta.openshift.io/serving-cert-secret-name=maas-gateway-tls \
  --overwrite

oc get secret maas-gateway-tls -n openshift-ingress
# Should show TYPE kubernetes.io/tls
```

### Configure TLS for Authorino

Generate a serving certificate and enable TLS on the Authorino listener:

```bash
oc annotate service authorino-authorino-authorization \
  -n kuadrant-system \
  service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert \
  --overwrite

oc patch authorino authorino -n kuadrant-system --type=merge --patch '{
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

oc -n kuadrant-system set env deployment/authorino \
  SSL_CERT_FILE=/etc/ssl/certs/openshift-service-ca/service-ca-bundle.crt \
  REQUESTS_CA_BUNDLE=/etc/ssl/certs/openshift-service-ca/service-ca-bundle.crt
```

### Enable User Workload Monitoring

MaaS requires User Workload Monitoring for usage metrics. If it is not
already enabled on your cluster:

```bash
oc apply -f - <<'EOF'
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

### Enable MaaS in the DataScienceCluster

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

### Enable MaaS in the dashboard

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

### Verify deployment

```bash
oc get tenants.maas.opendatahub.io default-tenant \
  -n models-as-a-service \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# Expected: True
```

If it shows `False`, check the condition message for what is missing:

```bash
oc get tenants.maas.opendatahub.io default-tenant \
  -n models-as-a-service \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'
```

## Part 3: Publish a model to MaaS

The simplest path is the RHOAI dashboard wizard. Navigate to your project's
**Deployments** tab, click **Deploy model**, and select **Publish as MaaS**
in the Advanced settings. This creates a `MaaSModelRef` that registers the
model with the MaaS gateway.

If your gpt-oss-20b model from Path A is already deployed as a standalone
`InferenceService`, you can deploy a new instance using `LLMInferenceService`
(llm-d) or vLLM through the dashboard, and publish it as MaaS in the same
wizard.

!!! tip "vLLM runtime for MaaS"
    MaaS supports both llm-d and vLLM runtimes. vLLM on MaaS is Tech
    Preview in 3.4. To enable it, set
    `spec.dashboardConfig.vLLMDeploymentOnMaaS: true` in
    `OdhDashboardConfig`. If your cluster has limited GPU and you don't need
    llm-d's distributed inference features, vLLM is the simpler choice.

Verify the model was published:

```bash
oc get maasmodelref -n <your-project-namespace>
```

## Part 4: Create a subscription and authorization policy

MaaS uses two resources to control access:

- **MaaSSubscription** -- grants groups quota for models with token limits
- **MaaSAuthPolicy** -- authorizes groups to access model endpoints through
  the gateway

Both are required. A subscription without an auth policy results in 403
errors.

### Create a subscription

In the RHOAI dashboard, navigate to **Settings > Subscriptions** and click
**Create subscription**:

1. **Name:** `calculus-dev`
2. **Priority:** `0` (development tier)
3. **Groups:** select or create a group (e.g., `calculus-users`)
4. **Add models:** select the gpt-oss-20b model you published
5. **Token limit:** 50,000 tokens per hour
6. Check **Create a matching authorization policy**
7. Click **Create subscription**

Or via CLI:

```yaml
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSSubscription
metadata:
  name: calculus-dev
  namespace: models-as-a-service
spec:
  priority: 0
  groups:
    - calculus-users
  models:
    - name: <maasmodelref-name>
      namespace: <model-namespace>
      tokenLimits:
        - limit: 50000
          window: 1h
```

```bash
oc apply -f maas-subscription.yaml
```

!!! note "Groups"
    MaaS validates access against OpenShift groups. Create the group and add
    your user if it doesn't exist:
    `oc adm groups new calculus-users <your-username>`

### Verify the subscription

```bash
oc get maassubscriptions -n models-as-a-service
# Phase should be Active
```

## Part 5: Get an API key and test

Create an API key through the RHOAI dashboard: navigate to **Gen AI studio >
API keys**, click **Create API key**, select the `calculus-dev` subscription,
and save the generated `sk-oai-*` key.

Or via the MaaS API:

```bash
MAAS_HOST=$(oc get gateway maas-default-gateway -n openshift-ingress \
  -o jsonpath='{.status.addresses[0].value}')

OCP_TOKEN=$(oc whoami -t)

API_KEY=$(curl -sk "https://${MAAS_HOST}/maas-api/v1/api-keys" \
  -H "Authorization: Bearer ${OCP_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name": "calculus-agent", "expiration": "30d"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")

echo "API key: ${API_KEY}"
```

!!! warning "Save the key"
    The full API key is shown only at creation time. Store it securely.

Test inference through the MaaS gateway:

```bash
curl -sk "https://${MAAS_HOST}/maas-api/v1/chat/completions" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RedHatAI/gpt-oss-20b",
    "messages": [{"role": "user", "content": "In one short sentence, say hello."}],
    "max_tokens": 300
  }' | python3 -m json.tool
```

You should see the same response format as Path A.

## Part 6: Wire the calculus-agent to MaaS

The agent code is identical -- only environment variables change:

| Variable | Path A (direct vLLM) | MaaS |
|----------|---------------------|------|
| `MODEL_ENDPOINT` | `http://gpt-oss-predictor.gpt-oss-model.svc.cluster.local:8000/v1` | `https://<maas-gateway-host>/maas-api/v1` |
| `MODEL_NAME` | `RedHatAI/gpt-oss-20b` | `RedHatAI/gpt-oss-20b` (unchanged) |
| `OPENAI_API_KEY` | (not set or dummy) | `<your-maas-api-key>` |

Update the agent's ConfigMap and create a Secret for the API key:

```bash
MAAS_HOST=$(oc get gateway maas-default-gateway -n openshift-ingress \
  -o jsonpath='{.status.addresses[0].value}')

oc patch configmap calculus-agent-config \
  -n calculus-agent \
  --type merge -p "{
    \"data\": {
      \"MODEL_ENDPOINT\": \"https://${MAAS_HOST}/maas-api/v1\"
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
| Model runtime | KServe `InferenceService` | `LLMInferenceService` (llm-d) or vLLM via dashboard |
| Endpoint | In-cluster Service URL | MaaS gateway with auth |
| Authentication | None (in-cluster trust) | API key (`sk-oai-*`) via Authorino |
| Quota management | None | Subscription-based token limits per group |
| Access control | None | `MaaSAuthPolicy` per group per model |
| Cost visibility | None | Token consumption metrics and CSV export |
| Multi-model | One InferenceService per model | One gateway, many models |
| Agent code changes | -- | None (env vars only) |

## What's next

- [MCP Gateway](mcp-gateway.md) -- centralize access to MCP servers through a
  governed gateway, the same way MaaS centralizes model access
- [Where to Go Next](../where-next.md) -- the full picture of what comes after
  this tutorial
