# Retrospective: Upstream skill improvements

**Date:** 2026-04-16
**Effort:** Close the two systemic process-gap action items from the previous retro by expanding the `/update-docs` and `/deploy-mcp` slash-command skills in the upstream template, then sync the fork so both remotes carry the fixes.
**Commits (redhat-ai-americas/mcp-server-template):** `33d53bc` (`/update-docs`), `b5b27fd` (`/deploy-mcp`)
**Fork sync (rdwj/mcp-server-template):** fast-forward to `b5b27fd`, +49 commits / +7052 lines / −823 lines
**Prior retro:** [2026-04-16_calculus-helper-build/RETRO.md](../2026-04-16_calculus-helper-build/RETRO.md)

## What We Set Out To Do

Turn the previous retro's "process gaps" into code changes:

- Make `/update-docs` actually sweep for template-language drift across all docs — not just README/ARCHITECTURE.
- Make `/deploy-mcp` force live verification via mcp-test-mcp instead of letting the main agent treat the terminal-worker's "pod ready" report as done.
- Propagate both fixes to the `rdwj/mcp-server-template` fork.

## What Changed

| Change | Type | Rationale |
|---|---|---|
| `/update-docs` split into three mandatory phases (component docs, drift sweep, test-file sanity) | **Systemic fix** | Old skill stopped at README/ARCHITECTURE; downstream projects had stale "MCP Server Template" self-references in six files. Now explicitly: "Phase 1 alone is not done." |
| `/deploy-mcp` — mcp-test-mcp availability check moved from Phase 4 to Phase 1 | **Structural fix** | Old skill discovered missing verification tooling after deploying. Now: if you can't verify, you don't build. |
| `/deploy-mcp` — Phase 4 live verification made a concrete tool sequence with assertions (connect → list_tools schema-assert → happy path → error path → disconnect) | **Structural fix** | Old skill said "verify with mcp-test-mcp" but didn't spell out what "verified" means. Now it means: schemas match, happy path returns expected shape, error path preserves `ToolError` coaching end-to-end through streamable-HTTP. |
| Terminal-worker prompt tightened — told explicitly NOT to declare the deploy complete | **Good pivot** | Initial framing was "make mcp-test-mcp mandatory." The actual root cause was structural: the worker's success message read as terminal to the main agent. The reframe produced a cleaner fix. |
| rdwj/mcp-server-template fast-forwarded from `e0605be` → `b5b27fd` | **Propagation** | Upstream (redhat-ai-americas) was carrying commits the fork hadn't received. Clean fast-forward, no divergent commits. |

## What Went Well

- **The memorised HITL threshold paid off.** User said "Let's do that too" for `/deploy-mcp` and I executed without re-consulting on scope. The whole effort was ~20 minutes of editing plus commits.
- **Commit messages carried their weight.** Both skill-expansion commits lead with root cause, then structural changes, then error-recovery additions. They'll still explain *why* in six months; that's the test.
- **Diagnosing structurally beat diagnosing symptomatically.** Reframing `/deploy-mcp` from "add requirements" to "close the flow gap that lets agents stop early" produced a better fix than a more mechanical patch would have.
- **Fork sync was a clean fast-forward.** The rdwj fork had no divergent commits, so no merge commit, no conflicts. Adding `upstream` as a persistent remote also sets up future syncs cleanly.
- **Pre-commit hook handling landed as a codified pattern.** `--no-verify` consent, once given for a repo/session/change-class, doesn't need to be re-asked — saved as a memory so it's durable.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| Local `test/mcp-server-template` checkout was 49 commits stale vs its own `origin/main` | **Accepted** | Local-workspace drift, not a sync problem with the fork itself. The fork on GitHub was current with upstream through `e0605be` already; I just brought it the last two commits. |
| Skills are untestable artifacts — we trust the markdown will be interpreted correctly by future agents | **Inherent** | No "unit test for a skill" exists. The real test is the next time someone runs `/update-docs` or `/deploy-mcp` against a fresh server. Worth writing a small runbook to exercise them periodically. |
| Public `redhat-ai-americas/mcp-server-template` has an internal Red Hat pre-commit hook configured (`rh-multi-pre-commit`) that external contributors can't satisfy | **Accepted (not ours to fix)** | User confirmed: "That hook was undergoing some changes so we took it out and started doing our own scanning. I'll eventually reinstall it." Flag-only, per CLAUDE.md rule about internal tooling on public repos. |

## Action Items

- [x] Expand `/update-docs` — done in `33d53bc`
- [x] Expand `/deploy-mcp` — done in `b5b27fd`
- [x] Sync rdwj fork — done, both remotes at `b5b27fd`
- [x] Save hook-skip consent pattern as a memory — done
- [ ] **Standing follow-up** (carried from previous retro, not closed here): regression test for `integrate` bound-ordering once user feedback indicates whether docs-only is sufficient

## Patterns

Second retro in this project.  Comparing to the first:

**Continue:**
- HITL threshold calibration — working well across two retros now. The explicit memory earned its keep this session.
- Commit messages that lead with root cause — a recognizable house style is forming.
- Task tracking **improved** mid-session (created a task for `/deploy-mcp` before starting it) but is still catch-up in places. Not yet the default habit.

**Start:**
- **Diagnose skill-definition bugs structurally, not symptomatically.** When a skill allows a failure mode, the fix is usually about flow structure, not adding more guardrail text. The `/deploy-mcp` reframe is the exemplar.
- **Treat consent as scope-bounded, not commit-bounded.** Explicit OK for `--no-verify` persists across same-repo / same-hook / same-class commits in one session.

**Stop:**
- Spinning up task tracking mid-effort. Start-of-task is the habit I want; mid-effort is the one I actually have. Still working on this.

## Meta

Two retros same day, closing the loop on the first. The pattern is working: retro identifies a systemic gap → gap becomes an action item → next session closes the action item → next retro verifies closure. Worth preserving as a deliberate cadence.
