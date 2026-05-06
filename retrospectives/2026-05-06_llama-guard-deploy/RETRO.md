# Retrospective: llama-guard-deploy

**Date:** 2026-05-06
**Effort:** Validate `configure-shields.md` Path B end-to-end with `RedHatAI/Llama-Guard-4-12B-quantized.w8a8`. Scale a second GPU, deploy Llama Guard, register the shield in OGX's Wave 2 ConfigMap, rewrite the doc to match what worked.
**Issues:** #27 (closed), #30 (refs — 2 new upstream drafts added)
**Commits:** d72ec80

Detailed technical findings are in `findings.md` (in this directory). This RETRO is the process companion.

## What We Set Out To Do

- Scale up a second GPU node on the validation cluster
- Deploy Llama Guard using the same pattern as `gpt-oss-20b` so it appears in the RHOAI dashboard
- Apply Wave 2 ConfigMap registering both `code-scanner` (Path A) and `llama-guard` (Path B) shields
- Update `configure-shields.md` Path B to match what worked
- Open issues for everything we know we need to do; draft (don't yet file) upstream issues

## What Changed

| Change | Type | Rationale |
|---|---|---|
| Started on A10G (24 GB), fell back to L40S (48 GB) | Good pivot | Tried the cheap option first; the multimodal vision tower in LG4 made the weight footprint larger than the bare quantized number suggested. ~10 minutes lost trying to save several hundred dollars a week — acceptable trade. |
| Switched from RHAIIS:3 to `vllm/vllm-openai:v0.20.1` for Path B | Good pivot | RHAIIS:3 ships vLLM 0.13; LG4 w8a8 needs ≥0.15 for newer compressed-tensors fields. Caught at first pod-start. Main `serve-an-llm.md` (gpt-oss-20b) unchanged. |
| Wave 2 ConfigMap shape iterated three times (`params.model` → `provider_resource_id` → `provider_shield_id`) | Discovery | Each iteration came from inspecting the running OGX pod's source. The original doc text was wrong about the field name. |
| Doc update scope grew (full Path B rewrite, not just model swap) | Scope expansion | Once `params.model` was identified as dead, the explanatory paragraph and ConfigMap example both had to change — couldn't ship a model swap with stale guidance. |

## What Went Well

- **Work-from-issues principle held.** Issues #27–#30 were filed before any cluster work started. Across A10G OOM → L40S scale → three ConfigMap iterations, we never lost track of the goal or the upstream-filing list.
- **Backgrounded poll + ScheduleWakeup pairing.** Long waits (image pulls, weight downloads, GPU driver install) didn't burn the main context — combined a `run_in_background` `until` loop with periodic wakeups, which let the conversation resume cleanly when state changed.
- **`findings.md` while details were fresh.** Wrote the technical retrospective with verbatim error messages, source-line references, and exact ConfigMap diffs *before* the cluster state changed — replicable by anyone with the manifests in hand.
- **Manifests committed.** `retrospectives/2026-05-06_llama-guard-deploy/manifests/` lets a future cluster set up the same config without re-deriving from scratch.
- **Cost-aware fallback was clean.** Scaled `gpu-us-east-2a` back to 0 the moment we knew it wouldn't fit — no idle A10G racking up charges while we worked elsewhere.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| Original Path B section shipped 2026-05-05 with "untested known-shape recipe" warning, but the recipe itself had wrong field names (`params.model` vs `provider_shield_id`) — the warning gave a false sense that it would "mostly work" | Accepted | This iteration's whole point. User's plan: validate on multiple clusters before declaring done (see #28). |
| `.claude/scheduled_tasks.lock` is tracked-able local agent state | Fix now | Add `.claude/` to `.gitignore`. |
| Two new upstream candidates (provider-side bugs) need filing | Follow-up | Drafted in #30; will file in a future session after researching contribution guidelines. |

## Action Items

- [ ] Add `.claude/` to `.gitignore` (minor housekeeping; not blocking).
- [ ] (Tracked in #28) Run automated tutorial walkthrough on a fresh cluster to flush remaining drift before human walkthrough (#29).
- [ ] (Tracked in #30) File Drafts 1–5 against the appropriate upstream repos.

## Patterns (vs prior retro 2026-05-05_install-ogx-test)

**Recurring**: both retros corrected silent-failure or surface-mismatch issues that no static review would have caught — `url:` vs `base_url:`, `params.model` vs `provider_shield_id`, ConfigMap-replaces-doesn't-merge, RHAIIS vLLM version skew. The class of bug is "doc looks plausible; first cluster contact shows it's wrong in a specific detail." Not formalizing a CLAUDE.md rule for it — the user's plan to validate on several clusters before declaring done covers this directly.

**Start:** Validate every tutorial section on multiple cluster instances before declaring it done.

**Stop:** (nothing specific this round)

**Continue:**
- File issues before starting work, then work from them
- Write `findings.md` while cluster state is live
- Use `ScheduleWakeup` + backgrounded polls for long-running cluster operations instead of synchronous waits
- Inspect the running pod's source when behavior contradicts docs — don't trust the prose, trust the code
