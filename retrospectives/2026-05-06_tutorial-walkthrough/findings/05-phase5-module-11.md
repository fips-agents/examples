# Phase 5 — verify Module 11 (Scaling Inference with llm-d)

**Date:** 2026-05-06
**Cluster:** `cluster-hpdl7-sandbox2435` (context `kagenti-memory-hub`); no llm-d currently deployed (Phase 0 tore down)
**Targets:** `docs/11-scaling-with-llm-d.md`
**Outcome:** One small finding (F22): Module 11's "Getting started" pointer at the upstream llm-d quickstart doesn't surface the OpenShift `restricted-v2` SCC issue Phase 0 hit. Otherwise clean — `1f40e27` already corrected the integration paragraph that Phase 0 surfaced, the version pins are historical floors (still accurate), external URLs resolve, integration claim verified end-to-end in Phase 0.

## What was checked

Module 11 is short and explicitly conceptual — line 5: *"This chapter is conceptual — there's no agent code change, and no required step."* The verifiable claims are:

1. **Integration paragraph** (lines 47-48 + 71-73) — the "add llm-d as a third entry in providers.inference[]" framing. Already corrected in commit `1f40e27` after Phase 0; cluster's current `ogx-config` confirms `providers.inference` is a list (today: 2 entries `vllm` + `vllm-guard`; Phase 0 demonstrated 3 cleanly).
2. **External URLs** — `llm-d.ai` (200), `github.com/llm-d/llm-d` (release v0.6.0 visible). Both fine.
3. **Version pins** — "v0.5+" appears twice (line 26 hierarchical KV offloading; line 60 scale-to-zero). These are historical floors (introduced-in claims), not stale floors. v0.6.0 is current; both features remain present. No edit needed.
4. **Conceptual claims about prefill/decode disaggregation, KV-cache routing, hierarchical offloading** — design-level statements about llm-d's architecture, not directly verifiable from the cluster but consistent with Phase 0's hands-on validation.

## Findings

### F22 — Module 11's "Getting started" doesn't warn about OpenShift `restricted-v2` SCC (medium) 🟡

`docs/11-scaling-with-llm-d.md:64-69`:

> The llm-d project documents its own quickstart and Kubernetes install. Two pages worth bookmarking:
>
> - [llm-d.ai](https://llm-d.ai) — the project home, with the latest version and architecture overview
> - [github.com/llm-d/llm-d](https://github.com/llm-d/llm-d) — source, releases, and the Kubernetes deployment manifests

Phase 0's F3 finding documented that the upstream quickstart's `vllm/vllm-openai` image crashloops on OpenShift's `restricted-v2` SCC out of the box (`PermissionError: '/.triton'` → `EngineCore failed to start` → CrashLoopBackOff). The fix is small (emptyDir mounts at `/.config` and `/.triton`), but a reader who follows Module 11's pointer to the upstream quickstart cold will hit this and think they've misconfigured their cluster.

The chapter being conceptual doesn't fully duck this — it explicitly recommends following llm-d's own docs, and llm-d's own docs don't (yet) address the OpenShift case. Phase 0's `findings/upstream-llm-d-openshift-scc.md` is drafted for upstream filing under `#30`; until it's filed and accepted, Module 11 readers on OpenShift have no signal.

**Suggested fix:** add a small `!!! note` block at the end of "Getting started" that:
- Names the issue (vanilla vLLM image expects writable `/.config` + `/.triton`; OpenShift's `restricted-v2` SCC blocks)
- Names the fix (emptyDir mounts on those paths)
- Points at this repo's `retrospectives/2026-05-06_tutorial-walkthrough/manifests/` for a working overlay until the upstream issue is filed and resolved

Light-touch — one paragraph, no doc-architecture changes. Same pattern as the warnings throughout `serve-an-llm.md` / `install-ogx.md` for cluster-shape gotchas.

## Summary table

| ID | Type | Files | Effort | Decision needed |
|---|---|---|---|---|
| F22 | OpenShift caveat | `docs/11-scaling-with-llm-d.md` (one note block) | Trivial-low | Yes (pointer placement: retrospectives manifest path or wait for upstream) |

That's the only finding. Module 11 is otherwise the cleanest pass since Phase 1.

## What this pass did NOT cover

- Live deployment of llm-d for end-to-end verification — no llm-d on the cluster (Phase 0 tore down). Phase 0 already covered the integration mechanics; re-deploying just to re-confirm what Phase 0 confirmed isn't a good use of cluster time.
- llm-d v0.6.0 release-note review beyond the component summary — the release exists at `gh release view v0.6.0 -R llm-d/llm-d` and shows component versions; tutorial doesn't pin specific image versions, so the per-component bumps don't surface drift here.

## Time + cost

- ~10 min wall time, no cluster mutations.
- One `gh release view`, one `curl https://llm-d.ai`, one read of the cluster's `ogx-config` ConfigMap to confirm `providers.inference` is a list.

## Bottom line

Phase 5 was light because Phase 0 did the heavy work (and `1f40e27` landed the prose fix). F22 is the only inline edit candidate. Phase 4's surprise (a substrate gap behind a "should be light" phase) didn't repeat here — the prose really is mostly conceptual and the integration mechanics really were validated in Phase 0.

After F22 lands, **all five phases of #28 are complete.**
