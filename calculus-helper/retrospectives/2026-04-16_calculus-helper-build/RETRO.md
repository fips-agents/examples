# Retrospective: calculus-helper MCP build

**Date:** 2026-04-16
**Effort:** Build a FastMCP 3.x server that offloads symbolic calculus to SymPy, carried end-to-end through the project's full workflow (plan → create → exercise → deploy → docs → system prompt → publish to a public GitHub repo).
**Commits:** `64b9b98` (template baseline) → `068ffc4` (server implementation) → `317b05d` (template-language scrub)
**Repo:** https://github.com/rdwj/calculus-helper-mcp-demo

## What We Set Out To Do

Build an MCP server providing calculus tools — differentiation, integration, limits, Taylor series, equation solving, ODEs, simplification, numerical evaluation — backed by SymPy. Goal: LLM agents get *computed* answers instead of pattern-matched hallucinations. No pre-existing issue or acceptance criteria; the requirement was framed in one sentence and the workflow was expected to turn it into a shippable server.

Secondary goal: exercise the template's full workflow sequence (`/plan-tools`, `/create-tools`, `/exercise-tools`, `/deploy-mcp`, `/update-docs`, `/write-system-prompt`) as a real stress test.

## What Changed

| Change | Type | Rationale |
|---|---|---|
| Added `src/calc.py` shared parsing/formatting layer | **Good pivot** | Decided without explicit HITL — the alternative (4 subagents inventing 4 slightly-different parsers and return shapes) was clearly worse. User confirmed this was the right call in retro: "HITL is very important, but it gets diluted when it's to ask questions you could easily answer with high trust." |
| Dropped SymPy's `split_symbols` transformer from the parser; added `log10`/`log2`/`arcsin`/`arctan` aliases to the whitelist | **Good pivot (bug fix)** | `/exercise-tools` caught that `log10(x)` was being silently parsed as `10*g*l*o*x`. Unit tests were green; the structural parser bug only surfaced when probing error paths as an agent would. |
| `solve_ode` IC-key function-name validation added | **Good pivot (bug fix)** | Same phase: `{"g(0)": "1"}` when solving for `f` was silently treated as `{"f(0)": "1"}`. Second silent correctness bug. |
| `integrate` docstring note for bound ordering (instead of an `assumptions`-list signal) | **Scope deferral** | Both options were presented; user chose docs-only. The "Case B (reversed bounds, positive integrand) vs Case C (correct bounds, negative integrand) return identical responses" ambiguity remains. Revisit if user feedback indicates it bites. |
| `tests/test_server_e2e.py` rewritten during deploy prep | **Missed requirement** | The inherited e2e test hardcoded example tool/resource/prompt names (`echo`, `japan_profile`, etc.). `remove_examples.sh` broke 33 tests. Should have been anticipated during `/create-tools` — the e2e test file was inherently example-coupled. |
| Template-language cleanup commit (317b05d) | **Missed requirement** | `/update-docs` scoped only to README/ARCHITECTURE. Six other files still said "MCP Server Template" (CONTRIBUTING, DEVELOPMENT_PROCESS, AGENTS, CLAUDE, Makefile help banner, .github/CODEOWNERS). User caught this and said: "This is what /update-docs is supposed to catch." |
| Upstream `/update-docs` skill expanded in `~/Developer/MCP/templates/mcp-server-template/.claude/commands/update-docs.md` | **Systemic fix** | The template's skill under-delivered on its original intent. Expanded with two new phases: template-language drift sweep (with classify-and-fix table) and test-file sanity check. All three phases required before declaring done. |
| `.gitignore` narrowed from `retrospectives/` to `retrospectives/2026-04-06_*/` | **Self-correction** | Earlier blanket exclusion was the simplest fix for the template-era retros but also prevented this project's retros from being committed. |

## What Went Well

- **Parallel subagent execution**: 4 Sonnet workers implemented 8 tools + 74 tests in ~6 minutes elapsed. Zero cross-worker conflicts because the shared-utility decision was made *before* spawning them.
- **`src/calc.py` paid off**: every coaching error message sounds the same, every return dict is shaped the same way. Agents can chain tools with no parsing on their side.
- **`/exercise-tools` earned its keep**: caught both silent correctness bugs (`log10` mangling, IC name mismatch). Unit tests would not have found either — they required thinking like an agent making likely mistakes, not just coverage.
- **Deployment was boring**: `make deploy PROJECT=calculus-helper-mcp` → OpenShift BuildConfig → pod running in under two minutes, no Mac/podman/x86_64 drama.
- **Live verification proved more than pytest could**: mcp-test-mcp round-trip against the real HTTPS route confirmed that `ToolError` coaching messages propagate through streamable-HTTP intact — the test suite can't verify that by construction.
- **Git hygiene**: two substantive commits with imperative subjects, "why" bodies, `Assisted-by: Claude Code (Opus 4.6)` trailers, no co-author, no signoff, no advertising. Gitleaks clean both pre-stage and staged.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| `/update-docs` didn't catch template-language drift outside README/ARCHITECTURE | **Process gap (systemic)** | Fixed upstream — expanded skill at `~/Developer/MCP/templates/mcp-server-template/.claude/commands/update-docs.md` with a full drift-sweep phase. Future projects scaffolded from the template benefit automatically. |
| `/deploy-mcp` skill declared success before the mcp-test-mcp verification step | **Process gap** | Worth raising upstream too — the current `/deploy-mcp` treats pod-healthy as done. mcp-test-mcp verification was documented but not made mandatory. **Follow-up**: consider the same treatment as `/update-docs` got. |
| Task-tool hygiene was inconsistent — got reminded three times to use TaskCreate/TaskUpdate | **My habit** | Accepted. Will keep trying to front-load task creation on multi-step work. |
| `test_server_e2e.py` example-coupling wasn't caught during `/create-tools` | **Process gap (mild)** | Now addressed in the new `/update-docs` Phase 3 (test-file sanity check). Could also be raised during `/create-tools` itself if worth the complexity there. |
| `integrate` bound-ordering ambiguity (Case B ≡ Case C response) remains | **Accepted (docs-only)** | User's call; revisit on real feedback. Not tested for — a regression test for `∫[1,0] x = -1/2` would lock the contract if we decide docstring-only is right forever. |
| Shared utility `src/calc.py` decision was made unilaterally | **Accepted** | User explicitly confirmed this was the right tradeoff. Captured in a `feedback_hitl_threshold` memory for future reference. |

## Action Items

- [x] Fix `/update-docs` skill upstream (done, in the template repo but not yet committed/pushed there — user may want to commit that separately)
- [x] Narrow `.gitignore` to let new retros commit
- [x] Save HITL-threshold feedback memory for durability across future sessions
- [ ] **Follow-up**: consider similar treatment for `/deploy-mcp` — require mcp-test-mcp verification before reporting success
- [ ] **Follow-up** (optional): regression test for `integrate` bound-ordering — only if we decide docstring-only is the permanent answer

## Patterns

First retro on this project — no patterns to compare against yet. Two template-era retros exist (`2026-04-06_fastmcp-3x-migration`, `2026-04-06_generator-template-update`) but they belong to the upstream template's own development history and are excluded via `.gitignore`.

**Start:** front-load task tracking on any multi-step work; don't wait for reminders.
**Stop:** declaring a skill "done" when its reporting step doesn't match its stated intent — surface the gap in the moment (as the user did here with `/update-docs`), but catch it sooner next time.
**Continue:** pairing `/create-tools` with `/exercise-tools` — the exercise phase found real bugs that unit tests couldn't. Worth the ~15 minutes every time.
