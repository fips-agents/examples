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

Each component is its own Deployment, Service, and Route. The UI is static
assets served behind a route. The gateway is a Go binary that proxies requests
to the agent. The agent and MCP server are what you built in Modules 1--4.

Two environment variables control the wiring:

| Variable | Set on | Points to |
|----------|--------|-----------|
| `BACKEND_URL` | Gateway | Agent's in-cluster Service URL |
| `API_URL` | UI | Gateway's external Route URL |

The gateway uses an internal service URL because it runs inside the cluster. The
UI uses the external route because it runs in the user's browser.

## Scaffold the gateway

```bash
fips-agents create gateway calculus-gateway
cd calculus-gateway && ls
```

```
Containerfile   Makefile        chart/          deploy.sh
go.mod          go.sum          main.go         redeploy.sh
```

The gateway is a minimal Go project. No framework, no generated code -- just
the standard library's `net/http` and `httputil` packages.

### The proxy handler

The entire gateway fits in `main.go`. Here's the core:

```go
package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
)

func main() {
	backend := os.Getenv("BACKEND_URL")
	if backend == "" {
		log.Fatal("BACKEND_URL is required")
	}

	target, err := url.Parse(backend)
	if err != nil {
		log.Fatalf("invalid BACKEND_URL: %v", err)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"status":"ok"}`))
	})
	http.Handle("/", proxy)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("gateway listening on :%s, proxying to %s", port, backend)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}
```

That's it. `httputil.NewSingleHostReverseProxy` does the heavy lifting --
it copies headers, streams request and response bodies, and handles hop-by-hop
headers correctly.

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
Containerfile   Makefile        chart/          deploy.sh
nginx.conf      public/         redeploy.sh     src/
```

The UI is a web application that provides a chat interface. It connects to the
gateway's `/v1/chat/completions` endpoint and streams responses back to the
user. The key configuration is `API_URL`, which tells the frontend where the
gateway lives.

!!! info "UI framework"
    The scaffolded UI uses a lightweight frontend stack. The important detail
    for this tutorial isn't the framework -- it's the deployment pattern. The
    UI is built into a container that serves static assets via nginx, with
    `API_URL` injected at container startup.

### How API_URL is injected

The UI needs to know the gateway's public URL at runtime, not build time (since
the URL differs per environment). The Containerfile uses an entrypoint script
that substitutes `API_URL` into the built assets before nginx starts:

```bash
#!/bin/sh
# entrypoint.sh -- runs at container startup (Linux containers only)
find /opt/app-root/src -name '*.js' \
  -exec sed -i "s|__API_URL__|${API_URL}|g" {} \;
exec nginx -g 'daemon off;'
```

This pattern avoids rebuilding the container for each environment.

## Deploy the gateway

Build and deploy the gateway to your namespace:

```bash
cd calculus-gateway
./deploy.sh calculus-agent
```

The deploy script creates the BuildConfig, builds the image, and deploys the
Helm chart. You need to set `BACKEND_URL` to the agent's in-cluster service
URL:

```bash
helm upgrade calculus-gateway chart/ \
  --set config.BACKEND_URL=http://calculus-agent:8080 \
  --reuse-values \
  -n calculus-agent
```

!!! note "In-cluster service DNS"
    `http://calculus-agent:8080` uses Kubernetes short-name DNS. This works
    when the gateway and agent are in the same namespace. For cross-namespace
    communication, use the fully qualified form:

        http://calculus-agent.<agent-namespace>.svc.cluster.local:8080

Verify the gateway is proxying correctly:

```bash
GW_ROUTE=$(oc get route calculus-gateway -n calculus-agent -o jsonpath='{.spec.host}')

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

```bash
cd calculus-ui
./deploy.sh calculus-agent
```

Then set `API_URL` to the gateway's external route:

```bash
helm upgrade calculus-ui chart/ \
  --set config.API_URL=https://$GW_ROUTE \
  --reuse-values \
  -n calculus-agent
```

!!! warning "HTTPS, not HTTP"
    `API_URL` must use `https://` because OpenShift routes terminate TLS at the
    edge. If you use `http://`, the browser will block the request as mixed
    content.

Get the UI route and open it in your browser:

```bash
UI_ROUTE=$(oc get route calculus-ui -n calculus-agent -o jsonpath='{.spec.host}')
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
  --overwrite -n calculus-agent

# Set 120-second timeout on the UI route
oc annotate route calculus-ui \
  haproxy.router.openshift.io/timeout=120s \
  --overwrite -n calculus-agent
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

1. The **UI** sends a POST to the gateway's `/v1/chat/completions` endpoint.
2. The **gateway** proxies the request to the agent's in-cluster service.
3. The **agent** calls `call_model()`, which sends the conversation to the LLM.
4. The **LLM** decides to call the `integrate` tool.
5. The **agent** dispatches the tool call over MCP to the calculus-helper server.
6. The **MCP server** runs SymPy and returns the result.
7. The **agent** feeds the result back to the LLM, which formats the answer.
8. The response streams back through the gateway to the UI.

The answer should show something like: **sin(x)^2 / 2 + C**.

Try a few more to exercise the full stack:

- "Differentiate ln(x^2 + 1)" -- tests the differentiate tool.
- "Evaluate the integral of 1/x from 1 to e" -- tests definite integration.
- "Find the second derivative of e^(2x)" -- tests higher-order derivatives.

If any request hangs or times out, check the route timeout annotation first.
Then check pod logs for each component in the chain:

```bash
oc logs deployment/calculus-ui -n calculus-agent --tail=20
oc logs deployment/calculus-gateway -n calculus-agent --tail=20
oc logs deployment/calculus-agent -n calculus-agent --tail=20
```

## Redeploying after changes

Each component follows the same rebuild cycle from Module 2:

```bash
# Gateway
cd calculus-gateway && make redeploy PROJECT=calculus-agent

# UI
cd calculus-ui && make redeploy PROJECT=calculus-agent
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

**UI layer.** Handles presentation, session state, and user preferences. It
can be replaced (a mobile app, a CLI, a Slack bot) without touching anything
behind the gateway.

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
