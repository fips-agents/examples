# Next Session

**Last refreshed:** 2026-05-06 (post Phase 0 of #28 walkthrough — llm-d install + OGX integration validated; cluster torn down)

## Where we are

Tutorial content is complete (12 modules + setup + reference) and now has a closing **["Where to Go Next"](docs/where-next.md)** page after Module 11 that points at kagenti as the layer above OGX. Module 11's "second LlamaStackDistribution / shadow-route" paragraph was wrong against a real OGX cluster — corrected (commit `1f40e27`) to describe what OGX actually does (third entry in `providers.inference[]`, no built-in traffic split).

**Phase 0 of #28 is done:** llm-d v0.6 installed on a temporary 3rd L40S, single-replica Qwen3-0.6B served, OGX wired as a third inference provider, end-to-end chat completion routed cleanly through OGX → llm-d → vLLM. Findings + reusable manifests in `retrospectives/2026-05-06_tutorial-walkthrough/`. Cluster fully torn down to pre-validation state.

Plan from here is unchanged: **multi-cluster validation before declaring tutorial-complete**. Phase 1 of #28 is the next slice of work.

## Open issues, in priority order

### 1. [#28 — Automated tutorial walkthrough (Modules 0–11)](https://github.com/fips-agents/examples/issues/28)

**Phase 0 complete** (this session). Remaining phases per the original plan:

| Phase | Targets | Notes |
|---|---|---|
| 1 (next) | Already-validated guides re-verified | `serve-an-llm`, `install-ogx`, `configure-shields` Path A+B — known-good against current cluster, quick re-verify |
| 2 | Setup guides not recently validated | `cluster-options`, `install-openshift-ai`, `install-cli-tools`, `registry-setup`, `observability-backends` |
| 3 | Modules 0–9 (BaseAgent core) | Cold-start path, heaviest pass — most likely place to find drift |
| 4 | Module 10 (guardrails + observability) | Verifies the doc tells the OGX story right |
| 5 | Module 11 (llm-d) | **Phase 0 covered the integration claim**; Phase 5 is just re-verifying Module 11's *prose* against current llm-d state |

Each drift gets filed as its own follow-up issue and either fixed in the same pass or linked from a fix-up PR.

### 2. [#30 — File upstream issues](https://github.com/fips-agents/examples/issues/30)

Original five drafts (against `meta-llama/llama-stack` and `ogx-ai/ogx-k8s-operator`) still pending. **Two new llm-d drafts added this session**, stored separately at:

- `retrospectives/2026-05-06_tutorial-walkthrough/findings/upstream-llm-d-doc-drift.md` — README on `main` references guides not present in tag `v0.6.0`
- `retrospectives/2026-05-06_tutorial-walkthrough/findings/upstream-llm-d-openshift-scc.md` — optimized-baseline manifests CrashLoopBackOff on OpenShift's `restricted-v2` SCC (vanilla `vllm/vllm-openai` needs writable `/.config` and `/.triton`)

Open question for next session: file the llm-d drafts under #30 (broaden its scope) or open a sibling tracking issue specifically for `llm-d/llm-d`? Either is fine; #30's title currently names two specific upstreams, so a sibling issue may be cleaner.

Filing happens in its own session — research each upstream repo's CONTRIBUTING/issue-template first; do not file before reading the rules of the room. (llm-d uses a Bug Report YAML template, no docs template — the two drafts are pre-formatted for it.)

### 3. [#29 — Human walkthrough](https://github.com/fips-agents/examples/issues/29) (blocked by #28)

Clean-room read-through for flow and clarity. Only worth scheduling once #28's automated pass is clean.

## Cluster state — `cluster-hpdl7-sandbox2435` (context: `kagenti-memory-hub`)

| Resource | Namespace | Notes |
|---|---|---|
| `InferenceService gpt-oss` | `gpt-oss-model` | `RedHatAI/gpt-oss-20b` on L40S #1 (RHAIIS:3) |
| `InferenceService llama-guard` | `llama-guard-model` | `RedHatAI/Llama-Guard-4-12B-quantized.w8a8` on L40S #2 (`vllm/vllm-openai:v0.20.1`) |
| `LlamaStackDistribution ogx` | `ogx` | Two providers (`vllm` + `vllm-guard`); shields registered |
| `MachineSet cluster-hpdl7-krtmj-l40s-us-east-2a` | `openshift-machine-api` | **2 replicas** (g6e.4xlarge × 2). Was scaled to 3 during Phase 0; restored. |
| `MachineSet cluster-hpdl7-krtmj-gpu-us-east-2a` | `openshift-machine-api` | 0 replicas (A10G unfit for LG4) |

Note: prior NEXT_SESSION.md used the friendly suffix `l40s-us-east-2a`; the actual cluster-prefixed name is `cluster-hpdl7-krtmj-l40s-us-east-2a`. Use the full name when scaling.

**Cost note:** the second L40S still costs ~$3.36/hr (~$560/week) idle. Same trade-off as before — Path B `llama-guard` invocations break if you scale `l40s-us-east-2a` back to 1 between sessions. Path A `code-scanner` is unaffected.

## Working artifacts to reuse

- `retrospectives/2026-05-06_tutorial-walkthrough/manifests/` — reusable kustomize overlay for llm-d on a single L40S, plus pre/post OGX `ogx-config` ConfigMaps (apply / revert)
- `retrospectives/2026-05-06_tutorial-walkthrough/findings/00-llm-d-phase0.md` — full Phase 0 finding list, time breakdown, teardown ledger
- `retrospectives/2026-05-06_llama-guard-deploy/manifests/` — verified Path B manifests (LG vLLM ServingRuntime + Wave 2 ConfigMap)
- `retrospectives/2026-05-05_install-ogx-test/manifests/gpt-oss-vllm.yaml` — gpt-oss-20b ServingRuntime
- `retrospectives/<dated>/findings.md` and `RETRO.md` — what surprised us last time, what process worked

## How to refresh this file

When this document goes stale, **delete and rewrite** rather than editing in place. Editing produces hybrids that mislead — the old `NEXT_SESSION.md` carried "all 8 modules" past the addition of Modules 10–11 and "reference model is granite" past the gpt-oss-20b switch, and both went unnoticed for sessions. A clean rewrite catches that.
