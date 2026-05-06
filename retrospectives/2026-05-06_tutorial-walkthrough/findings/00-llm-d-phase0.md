# Phase 0 — llm-d install + OGX integration validation

**Date:** 2026-05-06
**Cluster:** `cluster-hpdl7-sandbox2435` (context `kagenti-memory-hub`)
**llm-d version pinned:** main @ `bbf2654c780b63e105c03408822ed9bcc694bca2`
**Outcome:** Module 11's "add llm-d as a third inference provider in OGX" claim works end-to-end.

## What we validated

- llm-d Router (`quickstart-epp`) deploys and runs on a non-GPU node.
- llm-d model server (vLLM serving `Qwen/Qwen3-0.6B` at TP=1, 1 GPU) reaches Ready and answers `POST /v1/completions` correctly.
- Adding a third entry to `providers.inference[]` in `ogx-config` plus a matching entry in `registered_resources.models[]` is sufficient — no second `LlamaStackDistribution`, no controller-level reconciliation hack.
- OGX `/v1/models` lists the new `llm-d/Qwen/Qwen3-0.6B` after `oc rollout restart deploy ogx`.
- OGX `/v1/chat/completions` targeting `llm-d/Qwen/Qwen3-0.6B` routes through OGX → llm-d gateway → Qwen pod and returns a normal chat completion response.

## Findings worth filing

### F1 — Module 11 prose drift (FIXED)

Original paragraph claimed adding llm-d required a "second `LlamaStackDistribution`" pointed at the gateway, with OGX "shadow-routing a percentage of traffic." Both wrong:

- OGX is multi-provider in a single LSD by design. Add a third entry to `providers.inference[]`.
- OGX has no built-in percentage-based traffic split. A/B traffic splitting has to live one layer up (agent layer or HTTPRoute weights).

Fix: commit `1f40e27` rewrites the paragraph. New text says exactly what the platform does and bounds the "platform-mode" payoff honestly (provider switch is a config edit; traffic split isn't).

### F2 — llm-d README on `main` documents guides not present in tag `v0.6.0` (UPSTREAM, drafted)

`README.md` quickstart references `guides/optimized-baseline/...` but `git checkout v0.6.0` produces a tree without that directory (was reorganized to `inference-scheduling/` + `pd-disaggregation/` post-release). A user pinning to the latest release for reproducibility hits "No such file or directory" at the helm-install step.

Drafted as `findings/upstream-llm-d-doc-drift.md` — to be filed against `llm-d/llm-d` per their bug template.

### F3 — llm-d optimized-baseline manifests don't run on OpenShift's `restricted-v2` SCC out of the box (UPSTREAM, draft pending)

Vanilla `vllm/vllm-openai:v0.19.1` writes to `/.config` (vllm's `usage_lib`) and `/.triton` (Triton compiler cache) at filesystem root. Under OpenShift's `restricted-v2` SCC, the container runs as an arbitrary high UID and can't write to root-owned directories. Result: `PermissionError: [Errno 13] Permission denied: '/.triton'` → `EngineCore failed to start` → CrashLoopBackOff.

Upstream's overlay already mounts an emptyDir at `/.cache` for `torch.compile` — it's the same fix, applied to two additional paths. Our overlay (`manifests/llm-d-modelserver/patch-decode.yaml`) adds emptyDir mounts at `/.config` and `/.triton`. After that, vLLM boots normally.

llm-d's README has nightly OpenShift CI badge (`nightly-e2e-optimized-baseline-ocp.yaml`) so they presumably handle this in their CI overlay, but the documented quickstart doesn't surface this fix. Worth a second upstream issue — draft it before scaling down so we have the working diff in hand.

### F4 — Gateway API Inference Extension CRDs already present on RHOAI 3.x (NO ACTION)

The llm-d quickstart's `kubectl apply -k <GAIE CRDs>` step is a no-op on RHOAI 3.x clusters — RHOAI 3.2 ships `inferencepools.inference.networking.k8s.io` (v1) and the alpha sibling already. Skipping is safe; running it is also harmless. Not worth filing — accurate info, just slightly redundant for one specific install path.

## Effort breakdown

| Step | Wall time |
|---|---|
| Scale L40S MachineSet 2 → 3, node provisioning + GPU drivers | ~10 min |
| Helm-install llm-d Router | <1 min |
| Build + apply local kustomize overlay | ~3 min (initial) + ~3 min (SCC fix iteration) |
| Diagnose `ImagePullBackOff` (Docker Hub 504) — kubelet auto-retried | ~2 min wait |
| Diagnose `CrashLoopBackOff` (SCC PermissionError) | ~5 min |
| Apply OGX config patch + rollout restart | ~2 min |
| Smoke test through OGX | <1 min |
| **Total** | **~25 min active** |

## Manifests committed

- `manifests/llm-d-modelserver/kustomization.yaml` — pins to upstream main SHA
- `manifests/llm-d-modelserver/patch-decode.yaml` — single-GPU + Qwen3-0.6B + OpenShift SCC fixes
- `manifests/ogx-config-with-llm-d.yaml` — OGX config with three inference providers

## Teardown plan

User ask was "scale down once done." The full cleanup options:

| Cleanup | Cost saved | Reversibility |
|---|---|---|
| Scale L40S MachineSet 3 → 2 | ~$3.36/hr | Re-scale; node + drivers ~10 min |
| `helm uninstall quickstart -n llm-d-quickstart` | tiny (router on non-GPU node) | Re-helm install ~1 min |
| `oc delete namespace llm-d-quickstart` | trivial | Recreate + reinstall |
| Revert `ogx-config` to 2-provider state | none | Re-apply patch ConfigMap |

Minimum action covers the cost concern: scale MachineSet only. Leaving OGX configured with a `llm-d` provider that points at a non-existent gateway means OGX queries against `llm-d/Qwen/Qwen3-0.6B` will fail until the next reinstall — fine if no one targets that model.

Cleanest action restores the cluster to its pre-validation state. Recommend: **full teardown** (all four steps) so the cluster is in a known-good state for the next phase of #28.
