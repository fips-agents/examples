# Next Session

**Last refreshed:** 2026-05-06 (post Phases 1–3 of #28 + calculus-agent re-scaffold — already-validated guides re-verified, setup guides refreshed for RHOAI 3.3, Modules 0–9 audited and inline drift cleared, calculus-agent worked example brought to v0.11.1 template parity)

## Where we are

Tutorial content is complete (12 modules + setup + reference) plus the closing **["Where to Go Next"](docs/where-next.md)** page. Module 11's "second LlamaStackDistribution / shadow-route" paragraph was corrected against a real OGX cluster in commit `1f40e27`.

**Phases 1–3 of #28 are done** (this session). Six commits, all under `docs:`. State of the original 5-phase plan:

| Phase | Status | Notes |
|---|---|---|
| 0 (llm-d) | done | `findings/00-llm-d-phase0.md` |
| 1 (already-validated guides) | done | byte-for-byte match against live cluster — no drift |
| 2 (setup guides) | done | RHOAI 3.2→3.3 version pin, DSC YAML rewrite, dashboard-via-Gateway-API verify command, helm 4 |
| 3 (Modules 0–9) | done | 5 trivial edits + 1 paragraph rewrite + Module 6 sandbox swap; calculus-agent re-scaffolded from v0.11.1, F9+F10 resolved |
| 4 (Module 10) | next | Mostly re-verifiable against the live OGX install (Phase 1+2 already validated the substrate) |
| 5 (Module 11) | next | Mostly prose verification — Phase 0 covered the integration mechanics |

Per-phase findings under `retrospectives/2026-05-06_tutorial-walkthrough/findings/0[1-3]-*.md`.

## Open issues, in priority order

### 1. [#28 — Automated tutorial walkthrough (Modules 0–11)](https://github.com/fips-agents/examples/issues/28)

Phases 4 and 5 remain. Both are lighter than Phase 3 — Module 10's runtime substrate is already known-good (verified in Phases 1+2 as a side effect), and Module 11's integration claim was settled in Phase 0, leaving just prose verification.

### 2. [#30 — File upstream issues](https://github.com/fips-agents/examples/issues/30)

Original five drafts (against `meta-llama/llama-stack` and `ogx-ai/ogx-k8s-operator`) still pending. Two new llm-d drafts added in Phase 0:

- `findings/upstream-llm-d-doc-drift.md` — README on `main` references guides not present in tag `v0.6.0`
- `findings/upstream-llm-d-openshift-scc.md` — optimized-baseline manifests CrashLoopBackOff on OpenShift's `restricted-v2` SCC

Open question: file the llm-d drafts under #30 (broaden its scope) or open a sibling tracking issue specifically for `llm-d/llm-d`?

Filing happens in its own session — research each upstream's CONTRIBUTING / issue-template first.

### 3. [#29 — Human walkthrough](https://github.com/fips-agents/examples/issues/29) (blocked by #28)

Clean-room read-through for flow and clarity. Worth scheduling once Phases 4+5 of #28 land — the calculus-agent re-scaffold this session already closed the worked-example gap that would otherwise have tripped #29 immediately.

## What landed this session

| Commit | Subject |
|---|---|
| `db38120` | `docs: Add Phase 1 retrospective for #28 walkthrough` |
| `4292986` | `docs: Refresh setup guides for OpenShift AI 3.3 (#28 phase 2)` |
| `12672d3` | `docs: Update Modules 1/5/7/9 for v0.11.x scaffold + closed upstream issues (#28 phase 3)` |
| `2a75cb4` | `docs: Surface unused fips-agents create subcommands on Where to Go Next (#28)` |
| `c1efc56` | `docs: Switch Module 6 sandbox path to fips-agents create sandbox (F15, #28)` |
| `62a0bd2` | `docs: Refresh NEXT_SESSION.md after Phases 1–3 of #28` |
| `279312a` | `build: Anchor .claude/ gitignore rule to repo root` |
| `2e37e3c` | `refactor: Re-scaffold calculus-agent from v0.11.1 template (F9, F10, #28)` |

Phase 1 had no doc edits (clean). Phase 2 touched 3 setup guides (`cluster-options`, `install-cli-tools`, `install-openshift-ai`). Phase 3 + follow-ups touched 6 module/page files (`01-scaffold-agent`, `05-gateway-and-ui`, `06-code-sandbox`, `07-extend-with-ai`, `09-file-uploads`, `where-next`). The re-scaffold touched 23 files inside `calculus-agent/`, plus `.gitignore` (the prep that lets `.claude/commands/` actually commit).

## Cluster state — `cluster-hpdl7-sandbox2435` (context: `kagenti-memory-hub`)

Unchanged from last session — Phases 1–3 were audit-only, no resources mutated.

| Resource | Namespace | Notes |
|---|---|---|
| `InferenceService gpt-oss` | `gpt-oss-model` | `RedHatAI/gpt-oss-20b` on L40S #1 (RHAIIS:3) |
| `InferenceService llama-guard` | `llama-guard-model` | `RedHatAI/Llama-Guard-4-12B-quantized.w8a8` on L40S #2 (`vllm/vllm-openai:v0.20.1`) |
| `LlamaStackDistribution ogx` | `ogx` | Two providers (`vllm` + `vllm-guard`); shields registered |
| `Deployment jaeger` | `observability` | OTLP receiver for OGX traces; UI route reachable |
| `MachineSet cluster-hpdl7-krtmj-l40s-us-east-2a` | `openshift-machine-api` | **2 replicas** (g6e.4xlarge × 2). Untouched. |
| `MachineSet cluster-hpdl7-krtmj-gpu-us-east-2a` | `openshift-machine-api` | 0 replicas (A10G unfit for LG4) |

Note: `calculus-agent` and `calculus-mcp` namespaces exist but are **empty** — the worked examples have not been deployed in this cluster instance. Plan around that for #29 and for any phase that wants to verify cluster-side claims of Modules 1–9.

**Cost note:** the second L40S still costs ~$3.36/hr (~$560/week) idle. Same trade-off as before — Path B `llama-guard` invocations break if you scale `l40s-us-east-2a` back to 1 between sessions. Path A `code-scanner` is unaffected.

## Working artifacts to reuse

- `retrospectives/2026-05-06_tutorial-walkthrough/findings/00-llm-d-phase0.md` — Phase 0 finding list, time breakdown, teardown ledger
- `retrospectives/2026-05-06_tutorial-walkthrough/findings/01-phase1-already-validated-guides.md` — Phase 1 byte-for-byte verification table
- `retrospectives/2026-05-06_tutorial-walkthrough/findings/02-phase2-setup-guides.md` — Phase 2 RHOAI 3.3 drift catalog with line refs
- `retrospectives/2026-05-06_tutorial-walkthrough/findings/03-phase3-modules-0-9.md` — Phase 3 module audit; F9/F10/F15 detail and resolution rationale
- `retrospectives/2026-05-06_tutorial-walkthrough/manifests/` — reusable kustomize overlay for llm-d on a single L40S, plus pre/post OGX `ogx-config` ConfigMaps
- `retrospectives/2026-05-06_llama-guard-deploy/manifests/` — verified Path B manifests
- `retrospectives/2026-05-05_install-ogx-test/manifests/gpt-oss-vllm.yaml` — gpt-oss-20b ServingRuntime

## How to refresh this file

When this document goes stale, **delete and rewrite** rather than editing in place. Editing produces hybrids that mislead. A clean rewrite catches that.
