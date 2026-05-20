# MCP Gateway

In Module 4 you wired the calculus-agent directly to calculus-helper -- one
agent talking to one MCP server via an in-cluster Service URL. That works
fine for a single tool server, but production systems run dozens of MCP
servers, and you need a single point of control for authentication, rate
limiting, and tool discovery across all of them.

MCP Gateway is an Envoy-based proxy that federates multiple MCP servers
behind a single `/mcp` endpoint. Agents see one aggregated tool list;
platform teams get centralized governance. In this module you deploy MCP
Gateway, register calculus-helper behind it, add authentication, and rewire
the agent to connect through the gateway instead of directly.

!!! info "Prerequisites"
    - RHOAI 3.4 on OpenShift 4.19+
    - Modules 0--4 complete (agent and MCP server deployed and working)
    - calculus-helper accessible at its in-cluster Service URL
      (`mcp-server.calculus-mcp.svc.cluster.local:8080`)

!!! warning "Technology Preview"
    MCP Gateway is a Technology Preview feature in RHOAI 3.4, shipped via
    Red Hat Connectivity Link 1.3. CRDs are `v1alpha1` and subject to
    change. Only tools federation is supported -- prompts and resources
    federation is not yet available.

## What you will build

```
Current (Module 4):

  Agent ──> calculus-helper
            (direct Service URL)


After this module:

  Agent ──> MCP Gateway ──> calculus-helper
                │
                ├── Auth (K8s token review)
                ├── Rate limiting
                ├── Tool discovery
                └── Audit trail
```

## Part 1: Install Connectivity Link

Red Hat Connectivity Link 1.3 provides the Kuadrant control plane that
powers MCP Gateway. Install it from OperatorHub.

Create a namespace for the gateway infrastructure:

```bash
oc new-project mcp-gateway
```

Install the operator through the OpenShift console:

1. Navigate to **Operators > OperatorHub**
2. Search for **Red Hat Connectivity Link**
3. Select version **1.3** and install to **All namespaces**
4. Wait for the operator pod to reach `Running`

Verify the operator is ready:

```bash
oc get csv -n openshift-operators | grep connectivity-link
```

Gateway API CRDs ship natively with OpenShift 4.19+. Confirm they are
available:

```bash
oc get crd gateways.gateway.networking.k8s.io
oc get crd httproutes.gateway.networking.k8s.io
```

Both commands return the CRD metadata. If either is missing, your cluster
version is below 4.19 -- upgrade before continuing.

!!! note "Connectivity Link vs standalone Kuadrant"
    The RHOAI-supported path uses Red Hat Connectivity Link, which includes
    Kuadrant as a productized component. The upstream
    [Kuadrant project](https://github.com/Kuadrant/mcp-gateway) offers a
    standalone Helm install that works on any Kubernetes cluster, but it is
    not covered by Red Hat support.

## Part 2: Deploy the MCP Gateway

Three resources compose the gateway: a GatewayClass, a Gateway, and an
MCPGatewayExtension that binds MCP capability to the Gateway.

Create the GatewayClass:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: openshift-gateway
spec:
  controllerName: openshift.io/gateway-controller/v1
```

Create the Gateway with a listener for MCP traffic:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gateway
  namespace: mcp-gateway
spec:
  gatewayClassName: openshift-gateway
  listeners:
    - name: mcp-listener
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - name: mcp-gateway-tls
```

!!! tip "TLS certificate"
    OpenShift's ingress controller provisions a TLS certificate
    automatically when you use the default `openshift-gateway` class. If
    your cluster uses a custom CA, create the `mcp-gateway-tls` Secret
    manually before applying the Gateway.

Create the MCPGatewayExtension to enable MCP protocol handling on the
Gateway:

```yaml
apiVersion: mcp.kuadrant.io/v1alpha1
kind: MCPGatewayExtension
metadata:
  name: mcp-gateway
  namespace: mcp-gateway
spec:
  gatewayRef:
    name: mcp-gateway
    namespace: mcp-gateway
  sectionName: mcp-listener
```

Apply all three:

```bash
oc apply -f gatewayclass.yaml
oc apply -f gateway.yaml -n mcp-gateway
oc apply -f mcp-gateway-extension.yaml -n mcp-gateway
```

Wait for the Gateway to become ready:

```bash
oc wait --for=condition=Programmed gateway/mcp-gateway \
  -n mcp-gateway --timeout=120s
```

Get the gateway's external hostname:

```bash
GW_HOST=$(oc get gateway mcp-gateway -n mcp-gateway \
  -o jsonpath='{.status.addresses[0].value}')
echo "Gateway: https://${GW_HOST}/mcp"
```

Verify the `/mcp` endpoint is reachable. It returns an empty tool list
because no servers are registered yet:

```bash
curl -sf "https://${GW_HOST}/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python -m json.tool
```

## Part 3: Register calculus-helper

The calculus-helper deployed in Module 3 has an OpenShift Route for direct
access. MCP Gateway uses Gateway API HTTPRoutes for backend discovery.
Create an HTTPRoute that points at the same Service -- the existing Route
continues to work for direct access.

!!! tip "OpenShift Routes vs Gateway API HTTPRoutes"
    The tutorial's calculus-helper was deployed with an OpenShift Route
    (Module 3). MCP Gateway uses Gateway API HTTPRoutes for backend
    discovery. Both can coexist -- they point at the same Service, and
    neither interferes with the other.

Create the HTTPRoute:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: calculus-helper-route
  namespace: calculus-mcp
spec:
  parentRefs:
    - name: mcp-gateway
      namespace: mcp-gateway
      sectionName: mcp-listener
  rules:
    - backendRefs:
        - name: mcp-server
          port: 8080
```

Register the MCP server with the gateway:

```yaml
apiVersion: mcp.kuadrant.io/v1alpha1
kind: MCPServerRegistration
metadata:
  name: calculus-helper
  namespace: mcp-gateway
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: calculus-helper-route
    namespace: calculus-mcp
  prefix: calculus_
```

The `MCPServerRegistration` references an HTTPRoute in a different
namespace (`calculus-mcp`). If the Kuadrant controller enforces Gateway API
cross-namespace security, you may also need a `ReferenceGrant` in the
`calculus-mcp` namespace:

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-mcp-gateway
  namespace: calculus-mcp
spec:
  from:
    - group: mcp.kuadrant.io
      kind: MCPServerRegistration
      namespace: mcp-gateway
  to:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
```

Apply all resources:

```bash
oc apply -f calculus-httproute.yaml -n calculus-mcp
oc apply -f reference-grant.yaml -n calculus-mcp
oc apply -f calculus-registration.yaml -n mcp-gateway
```

Verify the gateway now exposes calculus-helper's tools:

```bash
curl -sf "https://${GW_HOST}/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python -m json.tool
```

The response lists all eight calculus tools, each prefixed with `calculus_`
(e.g., `calculus_differentiate`, `calculus_integrate`).

!!! note "Tool prefixing"
    The `prefix: calculus_` field namespaces all tools from this server.
    When you register multiple MCP servers, prefixing prevents name
    collisions -- if two servers both expose a `solve` tool, they become
    `calculus_solve` and `physics_solve`.

## Part 4: Configure access control

Use Kubernetes token review for authentication -- it requires no external
identity provider and works with any OpenShift cluster.

Create an AuthPolicy targeting the Gateway:

```yaml
apiVersion: kuadrant.io/v1
kind: AuthPolicy
metadata:
  name: mcp-auth
  namespace: mcp-gateway
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: mcp-gateway
  rules:
    authentication:
      k8s-token:
        kubernetesTokenReview:
          audiences:
            - mcp-gateway
```

Apply the policy:

```bash
oc apply -f auth-policy.yaml -n mcp-gateway
```

Confirm that unauthenticated requests are now rejected:

```bash
curl -s -o /dev/null -w "%{http_code}" "https://${GW_HOST}/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
# Expected: 401
```

Create a ServiceAccount and bound token for the agent:

```bash
oc create sa calculus-agent-sa -n mcp-gateway
TOKEN=$(oc create token calculus-agent-sa -n mcp-gateway \
  --audience=mcp-gateway --duration=24h)
```

Test that an authenticated request returns the tool list:

```bash
curl -sf "https://${GW_HOST}/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python -m json.tool
```

!!! note "Simplified auth for learning"
    Production deployments use full OIDC with Keycloak, Azure AD, or
    Okta -- the gateway supports these through Authorino's OAuth2
    integration. Kubernetes token review is simpler and doesn't require
    an external identity provider, making it appropriate for learning the
    gateway concepts.

## Part 5: Wire the agent through the gateway

The agent's `agent.yaml` still uses `mcp_servers:` with a URL -- the only
change is the URL itself, and optionally how auth headers are passed.

| Variable | Direct (Module 4) | Through MCP Gateway |
|----------|-------------------|---------------------|
| `MCP_CALCULUS_URL` | `http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/` | `https://<gateway-host>/mcp` |
| `MCP_GATEWAY_TOKEN` | (not set) | `<service-account-token>` |

Update the agent's ConfigMap with the gateway URL and token. If your agent
reads `MCP_CALCULUS_URL` from environment variables (the default
`agent.yaml` template does), update the ConfigMap:

```bash
oc set env deployment/calculus-agent \
  MCP_CALCULUS_URL="https://${GW_HOST}/mcp" \
  MCP_GATEWAY_TOKEN="${TOKEN}" \
  -n calculus-agent
```

If your `agent.yaml` needs to pass the token as a header, add the
`headers` field to the `mcp_servers` entry:

```yaml
mcp_servers:
  - url: ${MCP_CALCULUS_URL:-https://<gateway-host>/mcp}
    headers:
      Authorization: "Bearer ${MCP_GATEWAY_TOKEN}"
```

!!! warning "Verify the `headers` field"
    The `headers` field in `mcp_servers` is supported in fipsagents
    v0.11.0+. If your scaffolded agent uses an older version, check
    `agent.yaml` reference docs for the correct syntax.

Restart the agent to pick up the new environment:

```bash
oc rollout restart deployment/calculus-agent -n calculus-agent
oc rollout status deployment/calculus-agent -n calculus-agent --timeout=120s
```

Test end-to-end. Ask a calculus question and verify the agent discovers
tools through the gateway:

```bash
curl -s http://calculus-agent.calculus-agent.svc.cluster.local:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Differentiate x^3 + 2x"}]
  }' | python -m json.tool
```

The response should show tool calls to `calculus_differentiate` (note the
prefix) and a correct result.

!!! note "Same agent code, different plumbing"
    Like MaaS for model serving, MCP Gateway is an infrastructure concern.
    The agent's `agent.yaml` changes one URL. The MCP protocol is preserved
    end-to-end -- the gateway is transparent to the agent's tool-calling
    logic.

## Part 6: Verify governance

With traffic flowing through the gateway, you get centralized visibility
into tool usage.

Check the gateway's metrics endpoint for tool-call counts:

```bash
oc port-forward svc/mcp-gateway -n mcp-gateway 9090:9090 &
curl -s http://localhost:9090/metrics | grep mcp_tool_calls
kill %1
```

View request-level audit logs from the gateway pod:

```bash
oc logs -n mcp-gateway -l app=mcp-gateway --tail=50 | grep tool_call
```

Optionally, add a RateLimitPolicy to cap tool calls per client. This
example limits each ServiceAccount to 100 tool calls per minute:

```yaml
apiVersion: kuadrant.io/v1
kind: RateLimitPolicy
metadata:
  name: mcp-rate-limit
  namespace: mcp-gateway
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: mcp-gateway
  limits:
    tool-calls:
      rates:
        - limit: 100
          window: 1m
      counters:
        - expression: auth.identity.sub
```

```bash
oc apply -f rate-limit-policy.yaml -n mcp-gateway
```

## What changed

| Aspect | Direct (Module 4) | MCP Gateway |
|--------|-------------------|-------------|
| Connection | Agent to MCP server Service URL | Agent to Gateway to MCP server |
| Tool discovery | Per-server, agent manages each URL | Aggregated, single `/mcp` endpoint |
| Authentication | None (in-cluster trust) | Gateway-enforced (K8s token review) |
| Rate limiting | None | Per-user, per-tool rate policies |
| Tool namespacing | N/A | Automatic prefix per server |
| Audit trail | Application-level logging only | Gateway-level metrics and logs |
| Adding a new MCP server | Edit `agent.yaml`, redeploy agent | Create MCPServerRegistration, agent auto-discovers |
| Agent code changes | -- | None (URL and env vars only) |

## What's next

- [Models as a Service](maas-model-serving.md) -- centralize model access
  through a governed gateway, the same way MCP Gateway centralizes tool access
- [Agent Memory with MemoryHub](agent-memory.md) -- add cross-session
  memory so the agent retains user preferences and prior results
- [Where to Go Next](../where-next.md) -- the full picture of what comes
  after this tutorial
