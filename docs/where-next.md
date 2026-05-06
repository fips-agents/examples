# Where to Go Next

You finished the tutorial with a working agent platform: a BaseAgent talking to an MCP server, an OGX [LlamaStackDistribution](guides/install-ogx.md) handling tool orchestration and shields, vLLM serving the model, and (in Module 11) an awareness of how llm-d slots in when one model server stops being enough.

That stack covers a real shape of agent system. It does *not* cover every shape. This page names the next layer up — what you'd reach for when the tutorial's architecture stops being the right fit — and points at one specific project worth knowing about.

## What this tutorial does not cover

A few problems live one rung above the OGX-shaped platform you've built:

- **Agent-to-agent (A2A) communication.** The tutorial's agent talks to *tools* (MCP) and to a *model* (via OGX). It does not talk to *other agents*. Multi-agent systems — where one agent delegates to another, or several specialists collaborate — need a different protocol surface.
- **Workload identity and zero-trust.** Module 8 covers OpenShift Secrets and FIPS posture. It does not cover SPIFFE/SPIRE-style cryptographic identity for each agent and tool, or fine-grained authorization at the request level (which user is calling which tool through which agent, and is that allowed).
- **Gateway-level policy across many MCP servers.** Module 5 deploys one MCP server behind one gateway. Production fleets run dozens of MCP servers and want a single ingress that enforces auth, rate limits, and routing across all of them.
- **Multi-framework agent runtime.** This tutorial uses BaseAgent. Real organizations end up with LangGraph in one team, CrewAI in another, AutoGen in a third — and want one platform to deploy them all consistently.

You can solve any of these on top of OGX with custom code. At a certain scale, "custom code" stops scaling, and a platform layer above OGX starts paying for itself.

## Kagenti

[Kagenti](https://github.com/kagenti/kagenti) (not to be confused with `kagent` or `kagents` — the spelling matters) is an open-source, Apache 2.0 cloud-native middleware for exactly this layer. It's IBM-led with a public Slack and an active CI matrix that includes OpenShift HyperShift, and at the time of writing the latest release is **v0.5.1** (March 2026).

Kagenti organizes its work into four pillars on top of Kubernetes / OpenShift:

| Pillar | What it provides |
|---|---|
| **Lifecycle Orchestration** | Build agents from source (Shipwright), deploy as Kubernetes workloads, an admission webhook that wires platform services in, an `AgentCard` CRD for discovery |
| **Networking** | MCP Gateway (via [Kuadrant](https://github.com/Kuadrant/mcp-gateway)) for unified MCP routing and policy, Istio Ambient service mesh, Gateway API ingress |
| **Security** | Workload identity via SPIFFE/SPIRE, AuthBridge for OAuth/OIDC patterns, Keycloak integration |
| **Observability** | Tracing into MLflow / Langfuse / Phoenix, network visualization with Kiali |

The protocol surface is **A2A + MCP** — the same MCP you're already using for tools, plus the [A2A spec](https://google.github.io/A2A) for agent-to-agent communication. Agents written in LangGraph, CrewAI, AutoGen, Marvin, or anything else with an A2A endpoint can be deployed and orchestrated through Kagenti without rewriting them.

The canonical entry point is the [Weather Agent demo](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md) — it walks you through deploying an agent and a tool through the Kagenti UI and chatting with them end-to-end. Start there before you read any of the architecture docs.

## Before you install

Kagenti is a real platform, not a library. A few things to know before you `helm install` it on a cluster that's already running RHOAI:

!!! warning "This stack is pre-1.0"
    Kagenti v0.5.x is on the runway to a stable release, not at one. Install commands, CRD shapes, and component versions will change. Pin to a tagged release (`git checkout v0.5.1`), and budget for re-validation when you upgrade — the same kind of churn this tutorial has been through, on a project that hasn't yet declared API stability.

**Two service meshes do not coexist for free.** RHOAI ships its own Istio (in `Sidecar` mode, used by Knative and KServe). Kagenti expects Istio Ambient. Co-installing both on one cluster is not a documented happy path on either side. If you're adding Kagenti to a cluster that already runs the tutorial stack, plan to spend real time on mesh integration before anything else works.

**The OpenShift install path exists but is secondary.** Kagenti's primary documented install target is Kind (a local Kubernetes cluster) via an Ansible-driven installer. There's an [OpenShift install guide](https://github.com/kagenti/kagenti/blob/main/docs/install.md) and CI runs against OCP 4.20.11, but the day-to-day developer flow assumes Kind. Set expectations accordingly.

**Resource footprint is non-trivial.** SPIRE, Keycloak, Istio Ambient, Shipwright, and the Kagenti UI on top of an already-loaded RHOAI + OGX cluster is a lot. Plan capacity before you start.

The Kagenti maintainers track these issues in the open and respond on their [Slack](https://ibm.biz/kagenti-slack). If you're seriously evaluating it, that's the place to ask installation questions before you debug them solo.

## Other pointers

A handful of specs and projects are worth knowing about even if you don't deploy them:

- **[A2A protocol](https://google.github.io/A2A)** — the agent-to-agent communication spec. Read this before designing any multi-agent system, regardless of platform choice.
- **[MCP specification](reference/mcp-protocol.md)** — the protocol you've been using all along. The reference page in this tutorial covers the tutorial-relevant subset; the [official spec](https://modelcontextprotocol.io) covers the full surface.
- **[Kuadrant MCP Gateway](https://github.com/Kuadrant/mcp-gateway)** — the gateway component Kagenti uses, but usable standalone if you want unified MCP ingress without the rest of the platform.
- **[llm-d](https://llm-d.ai)** — covered conceptually in [Module 11](11-scaling-with-llm-d.md). Worth reading the project's own architecture docs before you decide you need it.

## What this means for the tutorial

Nothing changes in what you've already built. The OGX-shaped architecture from Modules 1–11 is a complete system on its own — Kagenti is what you'd graduate *to*, not something you've been missing. The order in this tutorial (single agent + MCP + OGX, then llm-d when you outgrow one vLLM, then Kagenti when you outgrow one agent) reflects the order most teams hit these problems in production. Don't deploy a layer you don't yet need.

If you build something with Kagenti on top of this tutorial's stack, that's exactly the kind of feedback issue the [`fips-agents/examples`](https://github.com/fips-agents/examples) tracker wants — what worked, what collided, what the docs should warn the next person about.
