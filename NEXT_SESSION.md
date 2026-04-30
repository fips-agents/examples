# Next Session: Post-Validation

## Context

Tutorial site: https://fips-agents.github.io/examples/
Repo: https://github.com/fips-agents/examples

All 8 modules + 5 reference pages + the new "Before You Begin" module + 5
setup guides are content-complete. The original automated end-to-end test
ran all modules against fips-rhoai with **Gemma 4** and fips-agents v0.8.1
— five doc issues were found, filed (fips-agents/examples#1-5), fixed,
and closed.

The April 2026 rebrand reframed the headline from "Building AI Agents for
OpenShift" to "Building AI Agents on Red Hat AI" and added the
prerequisites module + setup guides for cluster, OpenShift AI, vLLM
serving, CLI tools, and registry. The documented reference model is
**`ibm-granite/granite-3.3-8b-instruct`** — known to work with the
`fips-agents` framework and a good fit for FIPS-mode deployments.

## Current state

### Deployed on fips-rhoai

Full tutorial stack running in two namespaces (from the automated test run):

| Namespace | Components |
|-----------|-----------|
| `calculus-agent` | agent (2 replicas, sandbox sidecar), gateway, UI, HPA |
| `calculus-mcp` | MCP server (8 tools: integrate, differentiate, evaluate_limit, taylor_series, solve_equation, solve_ode, simplify_expression, evaluate_numeric) |

Old deployments in `ecosystem-test` and `calculus-helper` namespaces are
unrelated to the tutorial and still in use for other work.

### Known model behavior (historical)

The original Gemma 4 validation run surfaced two model-side quirks: empty
final content after tool calls, and malformed JSON for the `differentiate`
tool's `variables` array. Both are model issues, not tutorial issues, and
not expected to recur with Granite.

## Remaining work

1. **Human walkthrough** -- a manual read-through by someone who hasn't
   seen the material, checking flow and clarity. Particularly useful for
   the new `00-prerequisites.md` and `docs/guides/` pages, which haven't
   been student-tested.

2. **End-to-end re-verification on a fresh cluster** -- the prerequisites
   module and setup guides have not been walked through clean-room. A run
   from `00-prerequisites.md` → Module 9 against a fresh cluster would
   validate the new gating flow.

3. **Namespace cleanup (optional)** -- the `calculus-agent` and
   `calculus-mcp` test deployments can be torn down when no longer needed.

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
