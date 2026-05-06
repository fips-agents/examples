# Phase 3 — audit Modules 0-9 (BaseAgent core) against worked examples + scaffold reality

**Date:** 2026-05-06
**Mode:** Option B (audit-only, no cluster mutations) — modules vs. committed `calculus-agent/` + `calculus-helper/` + a fresh `fips-agents create agent` scaffold
**Workstation `fips-agents` version:** 0.11.1 (tutorial pins 0.11.0 in `docs/index.md:7`)
**Outcome:** 9 drift findings. 5 are trivial inline edits; 2 are upstream-issue closures landed since the modules were written; 2 need maintainer judgment about the worked example's role.

## What was checked

For each module, claims were checked against:
- Committed worked examples (`/Users/wjackson/Developer/AGENTS/examples/calculus-agent/`, `.../calculus-helper/`)
- A fresh scaffold (`fips-agents create agent test-agent --local --no-git --yes` in `/tmp/phase3-scaffold-test/`) — i.e., what a reader running Module 1 cold would see
- Upstream issue state via `gh` for the two open-issue references the modules carry (gateway-template#37, agent-template#100)

Cluster-side claims (`oc apply`, `helm install`, route URLs) were not re-verified — `calculus-agent` and `calculus-mcp` namespaces exist on the cluster but are empty (the worked examples were never deployed in this cluster, or were torn down before the Phase 0 record was created). End-to-end cluster verification is the right job for #29 (human walkthrough), not this pass.

## Findings

### F9 — `calculus-agent/` worked example lacks `.claude/commands/` (significant) 🟠

A fresh `fips-agents create agent` produces `.claude/commands/` with 7 files: `add-memory.md`, `add-skill.md`, `add-tool.md`, `create-agent.md`, `deploy-agent.md`, `exercise-agent.md`, `plan-agent.md`. The committed `calculus-agent/` worked example has **no** `.claude/` directory at all.

Module 7 makes the slash-command workflow central to "extend with AI." Module 1's CLAUDE.md (in the scaffolded output) advertises slash commands. A reader who follows Module 1 against `calculus-agent/` will see no slash commands in the worked example, then in Module 7 will be told to "run /plan-tools" against `calculus-helper/` (which does have them) — the inconsistency is jarring.

Either:
- The worked example was scaffolded before slash commands shipped in the agent template and was never re-scaffolded, or
- Slash commands were deliberately stripped before committing, or
- They're omitted by intent and the modules should not lean on them.

**Maintainer decision required.** Recommended fix: re-scaffold `calculus-agent/` against current `fips-agents` v0.11.x to bring `.claude/commands/` in; update Module 7 to show `/plan-agent` → `/create-agent` → `/exercise-agent` against the calculus-agent example (parallel to the `/plan-tools` flow against calculus-helper).

### F10 — `calculus-agent/agent.yaml` has empty `mcp_servers:` (significant) 🟠

`docs/04-wire-mcp-to-agent.md:38` is the entire payoff of Module 4: the user populates `mcp_servers:` with the calculus-helper service URL, rebuilds, and the agent picks up `integrate` / `differentiate` tools at startup. The committed `calculus-agent/agent.yaml` has:

```yaml
mcp_servers:
```

…empty. This means a reader using the worked example as the "what your end state should look like" reference will not see the configuration the module just walked them through producing.

**Maintainer decision required.** Same shape as F9 — likely re-scaffold + apply Module 4's edit, commit the result. Alternative: lean into the "worked examples are scaffolded outputs" framing in CLAUDE.md (top-level) and explicitly say in Module 4 that the committed example deliberately doesn't carry the wiring.

### F11 — `gateway-template#37` closed; Module 5 workaround now obsolete (inline-fixable) 🟡

`docs/05-gateway-and-ui.md:212-217` says:

> Roll the pod manually (the gateway template's chart is missing a `checksum/config` annotation — see `gateway-template#37` — so `helm upgrade --reuse-values` won't trigger a rollout).

`gh issue view 37 -R fips-agents/gateway-template` reports:

```
state:    CLOSED
closedAt: 2026-05-05T19:08:30Z
title:    bug: chart Deployment template missing `checksum/config` annotation;
          `helm upgrade --reuse-values` doesn't roll the pod
```

Closed yesterday. Readers using a current gateway-template scaffold no longer need the manual `oc rollout restart` workaround. Module 5 should either drop the caveat entirely or attach a "fixed in gateway-template vX, keep the workaround if pinned to earlier" version-aware note.

### F12 — `agent-template#100` closed; Module 9 "future directions" stale (inline-fixable) 🟡

`docs/09-file-uploads.md:135` says parsing runs inline; `:473-476` lists "background-queue parsing" as future work, citing `agent-template#100`. `gh issue view 100 -R fips-agents/agent-template` reports:

```
state:    CLOSED
closedAt: 2026-05-04T15:21:24Z
title:    feat: File upload endpoint with Docling parsing and pluggable storage
```

Closed two days ago. The "future" item is now present. Module 9's prose at `:135` (parse runs inline) may need a hedge ("by default") and the "Future directions" bullet at `:473-476` should be removed or rewritten with the actual landed behavior.

### F13 — Module 7 lists 5 agent slash commands; v0.11.x ships 7 (inline-fixable) 🟡

`docs/07-extend-with-ai.md:276-280`:

> Agent template ships with commands: /plan-agent, /create-agent, /exercise-agent, /add-tool, /add-skill

Fresh scaffold's `.claude/commands/`:

```
add-memory.md  add-skill.md  add-tool.md  create-agent.md
deploy-agent.md  exercise-agent.md  plan-agent.md
```

Two missing from the doc: `/add-memory`, `/deploy-agent`. Suggested fix: add both to the list.

### F14 — Module 7 lists 4 mcp-server slash commands; calculus-helper has 7 (inline-fixable) 🟡

`docs/07-extend-with-ai.md:18-28` shows the four-step pipeline `/plan-tools → /create-tools → /exercise-tools → /deploy-mcp`. `calculus-helper/.claude/commands/` actually contains 7 files (the four pipeline commands plus `/implement-mcp-item`, `/update-docs`, `/write-system-prompt`).

Suggested fix: keep the four-step pipeline diagram (it's the recommended path), but add a one-line note that the template also ships secondary commands and link to the directory. Don't try to expand the diagram — pipeline framing is the right teaching tool.

### F15 — Module 6 still says "clone external repo"; `fips-agents create sandbox` now exists (medium) 🟠

`docs/06-code-sandbox.md:55` instructs:

```bash
gh repo clone fips-agents/code-sandbox
```

…then `oc new-build` from that clone. But the current `fips-agents` CLI exposes:

```
$ fips-agents create --help
Commands:
  agent       Create a new AI agent project from template.
  gateway     Create a new API gateway project from template.
  mcp-server  Create a new MCP server project from template.
  model-car   Create a ModelCar project for packaging HuggingFace models.
  sandbox     Create a new code execution sandbox project from template.   ← new
  ui          Create a new chat UI project from template.
  workflow    Create a new workflow project from template.
```

**Maintainer decision required.** Three reasonable answers:
1. Switch Module 6 to `fips-agents create sandbox` (more aligned with the scaffold-everything pattern of Modules 1, 3, 5).
2. Keep `gh repo clone` (faithful to "this is the production sandbox image, not a per-tutorial scaffold").
3. Show both with a paragraph on when to use each.

The right answer depends on whether the `fips-agents create sandbox` template produces a *production-ready* sandbox or a *demo/learning* one. Worth verifying before flipping the doc.

### F16 — Module 1's `ls` output omits `.claude/` (inline-fixable) 🟡

`docs/01-scaffold-agent.md:35-39`:

```
AGENTS.md       CLAUDE.md       Containerfile   Makefile
README.md       agent.yaml      chart/          deploy.sh
evals/          prompts/        pyproject.toml  redeploy.sh
rules/          skills/         src/            tests/
tools/
```

A fresh scaffold also produces `.claude/`. The listing should include it. Suggested fix:

```
.claude/        AGENTS.md       CLAUDE.md       Containerfile
Makefile        README.md       agent.yaml      chart/
deploy.sh       evals/          prompts/        pyproject.toml
redeploy.sh     rules/          skills/         src/
tests/          tools/
```

Or use `ls -A` framing if hidden-file ordering bothers you.

### F17 — New `fips-agents create` subcommands not surfaced anywhere (informational) 🔵

`fips-agents create` includes `workflow` and `model-car` subcommands that no module references. These are likely v0.11+ additions. Not drift in the modules currently shipped — but a reader running `fips-agents create --help` will see them and wonder. Not a fix-up issue; consider a one-line "what's also available" note in `00-prerequisites.md` or the index "Where to Go Next" list.

## Summary table

| ID | Type | Files | Effort | Decision needed |
|---|---|---|---|---|
| F9  | Worked-example state | `calculus-agent/.claude/commands/` (missing) | Medium (re-scaffold + commit) | Yes |
| F10 | Worked-example state | `calculus-agent/agent.yaml` (empty `mcp_servers:`) | Medium (re-scaffold + Module 4 edit + commit) | Yes |
| F11 | Outdated upstream-issue ref | `docs/05-gateway-and-ui.md:212-217` | Trivial | No |
| F12 | Outdated upstream-issue ref | `docs/09-file-uploads.md:135, 473-476` | Trivial-Medium (rewrite a paragraph) | No |
| F13 | Stale enumeration | `docs/07-extend-with-ai.md:276-280` | Trivial | No |
| F14 | Stale enumeration | `docs/07-extend-with-ai.md:18-28` | Trivial | No |
| F15 | Workflow shifted under doc | `docs/06-code-sandbox.md:50-65` | Medium | Yes |
| F16 | Stale `ls` listing | `docs/01-scaffold-agent.md:35-39` | Trivial | No |
| F17 | Informational gap | `docs/00-prerequisites.md` or new | Trivial | Optional |

**Trivial inline edits (5):** F11, F13, F14, F16, F17.
**Needs a paragraph rewrite (1):** F12.
**Maintainer judgment (3):** F9, F10, F15.

## Time + cost

- ~25 min wall time, no cluster mutations, no scaling.
- One `gh issue view` per upstream reference.
- One disposable scaffold under `/tmp/phase3-scaffold-test/test-agent/` (can be removed: `rm -rf /tmp/phase3-scaffold-test`).

## What this pass did NOT cover

- End-to-end deploy of Modules 1→9 against a live cluster — saved for #29.
- `gh repo clone fips-agents/code-sandbox` content audit (current repo state vs. Module 6 prose).
- `fips-agents create sandbox` output audit (haven't compared to fips-agents/code-sandbox).
- Verification that `helm install … chart/` against the current chart still produces the values structure documented in Modules 2, 5, 6, 8, 9.
