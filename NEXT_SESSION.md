# Next Session: Post-Validation

## Context

Tutorial site: https://fips-agents.github.io/examples/
Repo: https://github.com/fips-agents/examples

All 8 modules + 5 reference pages + the new "Before You Begin" module + 5
setup guides are content-complete. An automated end-to-end test ran all
modules against fips-rhoai with **Gemma 4** and fips-agents v0.8.1. Five
doc issues were found, filed (fips-agents/examples#1-5), fixed, and
closed. The April 2026 rebrand reframed the headline from "Building AI
Agents for OpenShift" to "Building AI Agents on Red Hat AI" and added
the prerequisites module + setup guides for cluster, OpenShift AI, vLLM
serving, CLI tools, and registry. Gemma 4 9B is the documented reference
model.

## Current state

### Deployed on fips-rhoai

Full tutorial stack running in two namespaces (from the automated test run):

| Namespace | Components |
|-----------|-----------|
| `calculus-agent` | agent (2 replicas, sandbox sidecar), gateway, UI, HPA |
| `calculus-mcp` | MCP server (8 tools: integrate, differentiate, evaluate_limit, taylor_series, solve_equation, solve_ode, simplify_expression, evaluate_numeric) |

Old deployments in `ecosystem-test` and `calculus-helper` namespaces are
unrelated to the tutorial and still in use for other work.

### Known model limitation

Gemma 4 occasionally returns empty final content after tool calls, and fails to
construct valid JSON for the `differentiate` tool's `variables` array parameter.
A more capable model (Granite, Llama 3.3 70B) would handle these correctly.
This is not a tutorial issue and is now called out in `docs/guides/serve-an-llm.md`.

## Remaining work

1. **Human walkthrough** -- a manual read-through by someone who hasn't seen the
   material, checking for flow, clarity, and any steps that feel under-explained.
   Particularly useful for the new `00-prerequisites.md` and `docs/guides/`
   pages, which haven't been student-tested.

2. **End-to-end re-verification** -- the rebrand introduced no functional
   changes, but the prerequisites module and setup guides have not been
   walked through against a fresh cluster. A clean-room run from
   `00-prerequisites.md` → Module 9 would validate the new gating flow.

3. **Namespace cleanup (optional)** -- the `calculus-agent` and `calculus-mcp`
   test deployments can be torn down when no longer needed for manual testing.

## Namespace conventions (for reference)

| Component | Namespace | Pod/Service name |
|-----------|-----------|------------------|
| Agent | `calculus-agent` | `calculus-agent` |
| Gateway | `calculus-agent` | `calculus-gateway` |
| UI | `calculus-agent` | `calculus-ui` |
| MCP server | `calculus-mcp` | `mcp-server` |
| Sandbox | `calculus-agent` | sidecar in agent pod |

MCP URL: `http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/`
Sandbox image: `code-sandbox` (built via BuildConfig)
