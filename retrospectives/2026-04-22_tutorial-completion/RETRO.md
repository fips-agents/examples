# Retrospective: Tutorial Completion and E2E Validation

**Date:** 2026-04-22
**Effort:** Complete, consistency-fix, validate, and publish the 8-module tutorial
**Issues:** fips-agents/examples#1 through #5
**Commits:** 7457a45, 7fa3a66, c0358e0

## What We Set Out To Do

Finish remaining consistency fixes from a cross-module audit (namespace
standardization, ground truth file sync, sandbox image references, doc notes),
then publish to GitHub. The tutorial had been content-complete but unvalidated.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Namespace convention redesigned | Good pivot | User pointed out `my-namespace` collides and MCP servers should have "mcp" in the namespace name. Led to `calculus-agent` + `calculus-mcp` with FQDN URLs. |
| Added automated e2e test run | Good pivot | User suggested testing before manual walkthrough. Caught 5 blocking/significant doc issues. |
| Module 5 full rewrite | Scope expansion | E2e test revealed fips-agents v0.8.1 scaffolds had diverged from docs (Go project layout, Go-based UI server instead of nginx, different deploy commands). |
| Sandbox image: quay.io -> short name | Good pivot | No quay.io org exists; images built via BuildConfig. |

## What Went Well

- E2e test caught 3 blocking issues in Module 3 (curl headers, sympy dep) and a full architecture mismatch in Module 5 that reading alone wouldn't have found.
- Parallel sub-agent execution (Modules 1-2 alongside Module 3) cut test wall time.
- Filing GitHub issues before fixing gave trackable history and forced clear scoping.
- Namespace redesign produced a cleaner architecture (separate namespaces, descriptive names, FQDN URLs).
- All 5 issues filed, fixed, and closed in the same session.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Module 5 UI deploy path untested on cluster | Follow-up | UI scaffold lacks `make build-openshift`; documented manual `oc new-build` commands but didn't run them. fips-agents/examples#6 |
| MkDocs site rendering not verified | Follow-up | Pushed but nobody confirmed admonitions/code blocks/nav render correctly on the live site |
| Gemma model limitations mask potential issues | Accept | Empty responses and bad JSON for complex tool args could hide framework bugs; test with stronger model for higher confidence |
| Module 7 slash commands not exercised | Accept | E2e test wrote tools directly; `/plan-tools` etc. are workflow tools, not correctness requirements |
| No human has read the tutorial for narrative flow | Follow-up | Automated tests validate commands work but not that the story makes sense to a learner |

## Action Items

- [ ] fips-agents/examples#6 -- Test Module 5 UI deploy path on cluster
- [ ] Verify MkDocs site rendering (admonitions, code blocks, nav)
- [ ] Manual human walkthrough for narrative flow and clarity

## Patterns

First retro for this project.

**Start:** Run e2e validation against the actual CLI version before publishing docs. The template/doc drift in Module 5 would have been caught earlier.

**Stop:** Writing docs against assumed scaffold output. Always scaffold fresh and inspect actual files.

**Continue:** Filing issues before fixing, parallel sub-agent execution, asking the user for architectural decisions rather than assuming.
