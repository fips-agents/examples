# Next Session: End-to-End Validation

## Context

Tutorial site: https://fips-agents.github.io/examples/
Repo: https://github.com/fips-agents/examples

All content is written, reviewed, and published (commit 7457a45). The user is
doing an end-to-end test run of the tutorial to validate that the instructions
actually work as written.

## Before the next session

The user will walk through the tutorial from Module 1 to Module 8 on a fresh
cluster or namespace, following the docs exactly. Any issues found (wrong
commands, missing steps, unclear instructions) should be noted for the session.

## Likely next-session work

1. **Fix issues from test run** -- whatever the walkthrough surfaces
2. **Cluster cleanup** -- the ecosystem-test namespace on fips-rhoai uses old
   naming (`ecosystem-test-*`, `calculus-helper`). Redeploy with the new
   namespace conventions (`calculus-agent`, `calculus-mcp`) or tear down
3. **MkDocs site verification** -- confirm the published site renders correctly
   (admonitions, code blocks, nav structure)

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
