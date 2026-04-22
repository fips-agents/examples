# 5. Gateway and UI

Your agent responds to curl requests, but real users need a chat interface. In
this module you'll scaffold a Go gateway and a web UI, deploy both to OpenShift,
and wire them together so users can talk to your calculus agent through a
browser. You'll also learn why a gateway layer exists even when it starts as a
simple proxy.

## Architecture overview

Before scaffolding, here's how the pieces fit together:

```
Browser  ──▶  UI  ──▶  Gateway  ──▶  Agent  ──▶  MCP Server
  (chat)    (Route)    (Route)      (Service)     (Service)
```

Each component is its own Deployment, Service, and Route. The UI is a Go server
that serves static assets and proxies API calls to the gateway. The gateway is a
Go binary that proxies requests to the agent. The agent and MCP server are what
you built in Modules 1--4.

Two environment variables control the wiring:

| Variable | Set on | Points to |
|----------|--------|-----------|
| `BACKEND_URL` | Gateway | Agent's in-cluster Service URL |
| `API_URL` | UI | Gateway's in-cluster Service URL |

Both use internal service URLs because both the gateway and UI server run inside
the cluster. The UI server acts as a reverse proxy -- the browser never calls the
gateway directly.

## Scaffold the gateway

```bash
fips-agents create gateway calculus-gateway
cd calculus-gateway && ls
```

```
build/          CLAUDE.md       Containerfile   Makefile
README.md       chart/          cmd/            go.mod
internal/       planning/
```

The gateway is a structured Go project using only the standard library. The
handlers live in `internal/handler/`, configuration in `internal/config/`, and
the server entrypoint in `cmd/server/main.go`.

### The proxy handler

The interesting piece is the `ChatHandler` in `internal/handler/chat.go`, which
proxies `/v1/chat/completions` requests to the agent:

```go
// internal/handler/chat.go -- proxies /v1/chat/completions to the agent
package handler

import (
    "bytes"
    "io"
    "net/http"

    "github.com/fips-agents/calculus-gateway/internal/proxy"
)

type ChatHandler struct {
    BackendURL string
    Client     *http.Client
}

func (h *ChatHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    body, _ := io.ReadAll(r.Body)
    defer r.Body.Close()

    // Forward to backend
    req, _ := http.NewRequest(http.MethodPost, h.BackendURL+"/v1/chat/completions", bytes.NewReader(body))
    req.Header.Set("Content-Type", "application/json")
    resp, err := h.Client.Do(req)
    if err != nil {
        http.Error(w, `{"error":"backend request failed"}`, http.StatusBadGateway)
        return
    }
    defer resp.Body.Close()

    // Relay response (supports both sync JSON and SSE streaming)
    for k, v := range resp.Header {
        w.Header()[k] = v
    }
    w.WriteHeader(resp.StatusCode)
    io.Copy(w, resp.Body)
}
```

The full implementation in the scaffold handles streaming and sync modes
separately, with proper SSE relay for streaming responses (see
`internal/proxy/sse.go`). The code shown here is a simplified view of the
forwarding logic. The scaffold also includes health and readiness handlers
(`/healthz`, `/readyz`), request logging middleware, and configuration loaded
from environment variables.

### Why not just expose the agent directly?

The gateway looks redundant right now. It proxies requests without modification.
But it exists to be the future home of concerns that don't belong in the agent:

**Authentication.** Verify OAuth2/OIDC tokens before requests reach the agent.
The agent stays focused on reasoning; it never sees unauthenticated traffic.

**Rate limiting.** Protect the LLM backend from runaway clients. A single
middleware in the gateway applies limits across all agents behind it.

**Multi-agent routing.** When you have multiple agents (calculus, chemistry,
physics), the gateway inspects the request and routes to the right backend.
The UI doesn't need to know which agent handles which domain.

**Request logging and metrics.** Centralized access logs, latency histograms,
and error rates -- all in one place, independent of agent implementation
language.

!!! tip "Start thin, grow incrementally"
    Resist the urge to add middleware before you need it. Ship the proxy, get
    end-to-end working, then layer in auth and rate limiting when the
    requirements are clear.

## Scaffold the UI

```bash
fips-agents create ui calculus-ui
cd calculus-ui && ls
```

```
CLAUDE.md       Containerfile   Makefile        README.md
chart/          cmd/            go.mod          planning/
static/
```

The UI is a Go server that does two things: it serves the chat interface as
embedded static assets, and it acts as a reverse proxy for API calls to the
gateway.

!!! info "UI architecture"
    The scaffolded UI is a Go server that embeds static assets (HTML, JS, CSS)
    and acts as a reverse proxy for API calls. The browser talks only to the UI
    server -- no cross-origin requests needed. The chat interface includes SSE
    streaming, tool call visualization, and KaTeX math rendering.

The `static/` directory contains the frontend: `index.html`, `app.js`, and
`style.css`. These are embedded into the Go binary at build time using
`static/embed.go`.

### How the reverse proxy works

Instead of injecting the gateway URL into the frontend JavaScript, the UI server
proxies API requests itself. The browser makes all calls to the same origin --
the UI route -- and the Go server forwards `/v1/` requests to the gateway:

```go
// From cmd/server/main.go -- the key proxy setup
proxy := &httputil.ReverseProxy{
    Director: func(r *http.Request) {
        r.URL.Scheme = backendURL.Scheme
        r.URL.Host = backendURL.Host
        r.Host = backendURL.Host
    },
    FlushInterval: -1, // flush immediately for SSE streaming
}

mux.Handle("/v1/", proxy)          // API calls proxied to backend
mux.Handle("/", http.FileServer(http.FS(static.Files()))) // static assets
```

The browser calls `/v1/chat/completions` on the same origin as the UI. The Go
server proxies these requests to the backend. This avoids CORS issues entirely --
no cross-origin requests, no preflight checks. `API_URL` is set on the server
via an environment variable (typically through the Helm chart's ConfigMap), not
injected into the frontend JavaScript.

## Deploy the gateway

Build and deploy the gateway to your namespace:

```bash
cd calculus-gateway
make build-openshift PROJECT=calculus-agent
make deploy PROJECT=calculus-agent
```

`make build-openshift` creates a BuildConfig (if one doesn't already exist),
uploads the source, and builds the image in the cluster. `make deploy` runs
`helm upgrade --install` with the chart. You need to set `BACKEND_URL` to the
agent's in-cluster service URL:

```bash
helm upgrade calculus-gateway chart/ \
  --set config.BACKEND_URL=http://calculus-agent:8080 \
  --reuse-values \
  -n calculus-agent --kube-context=fips-rhoai
```

!!! note "In-cluster service DNS"
    `http://calculus-agent:8080` uses Kubernetes short-name DNS. This works
    when the gateway and agent are in the same namespace. For cross-namespace
    communication, use the fully qualified form:

        http://calculus-agent.<agent-namespace>.svc.cluster.local:8080

Verify the gateway is proxying correctly:

```bash
GW_ROUTE=$(oc get route calculus-gateway -n calculus-agent --context=fips-rhoai -o jsonpath='{.spec.host}')

# Health check (gateway's own endpoint)
curl -sk "https://$GW_ROUTE/healthz"
# {"status":"ok"}

# Proxied request to agent
curl -sk "https://$GW_ROUTE/v1/agent-info" | python -m json.tool
```

The `/v1/agent-info` response should match what you saw when hitting the agent
directly in Module 4. The request traveled: your machine --> gateway route -->
gateway pod --> agent service --> agent pod.

## Deploy the UI

The UI scaffold doesn't include a `build-openshift` Makefile target, so you
create the BuildConfig directly and build from source:

```bash
cd calculus-ui
oc new-build --binary --name=calculus-ui --strategy=docker \
  -n calculus-agent --context=fips-rhoai
oc patch bc/calculus-ui --patch '{"spec":{"strategy":{"dockerStrategy":{"dockerfilePath":"Containerfile"}}}}' \
  -n calculus-agent --context=fips-rhoai
oc start-build calculus-ui --from-dir=. --follow \
  -n calculus-agent --context=fips-rhoai
```

Once the image is built, deploy the Helm chart and point `API_URL` at the
gateway's **in-cluster** service URL:

```bash
IMAGE=$(oc get is calculus-ui -n calculus-agent --context=fips-rhoai \
  -o jsonpath='{.status.dockerImageRepository}')

helm upgrade --install calculus-ui chart/ \
  --set image.repository=$IMAGE \
  --set image.tag=latest \
  --set config.API_URL=http://calculus-gateway:8080 \
  -n calculus-agent --kube-context=fips-rhoai
```

!!! info "In-cluster URL, not external route"
    `API_URL` points to the gateway's **in-cluster** service URL because the
    UI server proxies API requests server-side. The browser never calls the
    gateway directly -- it sends requests to the UI origin, and the Go server
    forwards them.

Get the UI route and open it in your browser:

```bash
UI_ROUTE=$(oc get route calculus-ui -n calculus-agent --context=fips-rhoai -o jsonpath='{.spec.host}')
echo "https://$UI_ROUTE"
```

## Configure route timeouts

Agent responses can take 30 seconds or more, especially when the LLM chains
multiple tool calls. OpenShift's default route timeout is 30 seconds -- right
at the edge. You need to raise it on both the gateway and UI routes.

```bash
# Set 120-second timeout on the gateway route
oc annotate route calculus-gateway \
  haproxy.router.openshift.io/timeout=120s \
  --overwrite -n calculus-agent --context=fips-rhoai

# Set 120-second timeout on the UI route
oc annotate route calculus-ui \
  haproxy.router.openshift.io/timeout=120s \
  --overwrite -n calculus-agent --context=fips-rhoai
```

!!! warning "The silent 504"
    Without this annotation, complex queries that trigger multiple tool calls
    will return a 504 Gateway Timeout from HAProxy. The agent finishes the work
    successfully -- the client just never sees the response. This is one of the
    most common deployment surprises.

## Test end-to-end

Open `https://<UI_ROUTE>` in your browser. You should see a chat interface.
Type a calculus problem and watch the full chain execute:

```
You: What is the integral of sin(x)*cos(x)?
```

Here's what happens:

1. The **browser** sends a POST to the UI's `/v1/chat/completions` (same origin).
2. The **UI server** proxies the request to the gateway's in-cluster service.
3. The **gateway** proxies the request to the agent's in-cluster service.
4. The **agent** calls `call_model()`, which sends the conversation to the LLM.
5. The **LLM** decides to call the `integrate` tool.
6. The **agent** dispatches the tool call over MCP to the calculus-helper server.
7. The **MCP server** runs SymPy and returns the result.
8. The **agent** feeds the result back to the LLM, which formats the answer.
9. The response streams back through the gateway and UI server to the browser.

The answer should show something like: **sin(x)^2 / 2 + C**.

Try a few more to exercise the full stack:

- "Differentiate ln(x^2 + 1)" -- tests the differentiate tool.
- "Evaluate the integral of 1/x from 1 to e" -- tests definite integration.
- "Find the second derivative of e^(2x)" -- tests higher-order derivatives.

If any request hangs or times out, check the route timeout annotation first.
Then check pod logs for each component in the chain:

```bash
oc logs deployment/calculus-ui -n calculus-agent --context=fips-rhoai --tail=20
oc logs deployment/calculus-gateway -n calculus-agent --context=fips-rhoai --tail=20
oc logs deployment/calculus-agent -n calculus-agent --context=fips-rhoai --tail=20
```

## Redeploying after changes

Each component follows a build-then-deploy cycle:

```bash
# Gateway
cd calculus-gateway
make build-openshift PROJECT=calculus-agent
make deploy PROJECT=calculus-agent

# UI
cd calculus-ui
oc start-build calculus-ui --from-dir=. --follow \
  -n calculus-agent --context=fips-rhoai
make deploy PROJECT=calculus-agent
```

You can redeploy any component independently. The gateway doesn't need to
restart when you update the agent or MCP server -- it proxies to the service,
which automatically routes to the new pod after a rollout.

!!! tip "Order of deployment"
    When deploying the full stack for the first time, deploy bottom-up: MCP
    server first, then agent, then gateway, then UI. Each layer needs the one
    below it to be running. For subsequent updates, deploy only the components
    that changed.

## The gateway pattern

The three-tier architecture you've built (UI -- gateway -- agents) is a
common pattern in production agent systems. Here's why each layer exists:

**UI layer.** Handles presentation, session state, user preferences, and
proxies API calls to the gateway. It can be replaced (a mobile app, a CLI, a
Slack bot) without touching anything behind the gateway.

**Gateway layer.** The single point of entry for all clients. It owns
cross-cutting concerns: authentication, authorization, rate limiting, request
logging, and routing. When you add a second agent (say, a physics solver), the
gateway routes requests to the right backend based on the domain. Clients never
talk directly to agents.

**Agent layer.** Pure reasoning. Each agent connects to its own set of MCP
servers and tools. It exposes a standard `/v1/chat/completions` API. It doesn't
know about auth tokens, rate limits, or which UI is calling it.

This separation means you can scale, secure, and update each layer
independently. The gateway can enforce a 100-request-per-minute limit without
the agent knowing. The agent can swap its LLM backend without the UI caring.
The UI can be redesigned without touching any backend code.

## What's next

You have a complete user-facing system: browser to UI to gateway to agent to
MCP server. In [Module 6](06-code-sandbox.md), you'll add a code execution
sandbox that lets the agent write and run Python -- giving it the ability to do
numerical computation, generate data tables, and go beyond what symbolic tools
alone can handle.
