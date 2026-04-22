# Next Session: Post-Validation

## Context

Tutorial site: https://fips-agents.github.io/examples/
Repo: https://github.com/fips-agents/examples

All 8 modules + 5 reference pages are content-complete and validated. An
automated end-to-end test ran all modules against fips-rhoai with Gemma 4 and
fips-agents v0.8.1. Five doc issues were found, filed (fips-agents/examples#1-5),
fixed, and closed.

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
This is not a tutorial issue.

## Remaining work

1. **MkDocs site verification** -- confirm the published site at
   fips-agents.github.io/examples renders correctly (admonitions, code blocks,
   nav structure, code copy buttons). GitHub Actions should have rebuilt after
   the latest push.

2. **Human walkthrough** -- a manual read-through by someone who hasn't seen the
   material, checking for flow, clarity, and any steps that feel under-explained.

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
