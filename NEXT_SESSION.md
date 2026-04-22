# Next Session: Status

## Context

Tutorial site: https://fips-agents.github.io/examples/
Repo: https://github.com/fips-agents/examples

All 8 tutorial modules + 5 reference pages are content-complete (~4,300 lines
across 14 pages). All consistency issues from the cross-module audit have been
resolved.

## What's done

- All modules reviewed against answer-key code and corrected
- Full cross-module consistency audit completed and all issues resolved
- Ground truth files synced to end-of-Module-8 state
- Namespace conventions standardized:
  - Agent/gateway/UI deploy to `calculus-agent`
  - MCP server deploys to `calculus-mcp` (pod named `mcp-server`)
  - MCP URL uses FQDN: `http://mcp-server.calculus-mcp.svc.cluster.local:8080/mcp/`
- Sandbox image standardized to `code-sandbox` (short name, built via BuildConfig)
- Deploy mechanism orientation note added to Module 2
- Helm chart template name note added to reference docs

### Issues resolved

| ID | Issue | Fix applied |
|----|-------|-------------|
| C1 | Module 6 referenced `taylor_series` tool from Module 7 | Replaced with `differentiate` + sandbox test |
| C2 | Module 6 missing rebuild/redeploy section | Added build commands + agent-info showing 3 tools |
| C3 | `calculus-mcp` hostname in docs | Standardized to `mcp-server` (matches openshift.yaml) |
| C4 | Cross-namespace deployment | MCP deploys to `calculus-mcp`, agent to `calculus-agent`, URL uses FQDN |
| I1 | Module 6 opening skipped Module 5 | Now references "the chat UI you deployed in Module 5" |
| I2 | Answer-key files don't match tutorial | agent.yaml, system.md, code_executor.py all synced to end-of-Module-8 state |
| I3 | Trailing slash missing in Module 1 MCP URL | Fixed to `/mcp/` |
| I4 | Route timeout 300s in Module 8 vs 120s in Module 5 | Aligned Module 8 to `120s` |
| L1 | Module 1 foreshadowing used wrong hostname | Changed to `mcp-server` |
| L2 | Helm chart reference uses template name `ecosystem-test-agent` | Added explanatory note in helm-chart.md |
| L3 | Deploy command inconsistency | Added orientation callout in Module 2 |
| L4 | Module 4 table said "simplify with run_tool_calls()" | Changed to "Rename class for calculus domain" |
| L5 | Sandbox image reference inconsistency | Standardized to `code-sandbox` everywhere |

## What might still need attention

- **Cluster state**: The ecosystem-test namespace on fips-rhoai still uses the
  old naming. The tutorial docs are now ahead of the deployed state. Next
  deployment should use the new namespace names (`calculus-agent`, `calculus-mcp`).
- **Module 1 scaffold example**: `docs/01-scaffold-agent.md` line 96 still shows
  `http://mcp-server:8080/mcp/` as a generic scaffold example (not
  calculus-specific). This is intentional -- the scaffold template uses short
  names since namespace layout isn't known yet.
