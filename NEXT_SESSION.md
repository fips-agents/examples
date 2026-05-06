# Next Session

**Last refreshed:** 2026-05-06 (post Phases 1–5 of #28 + calculus-agent re-scaffold — full audit pass complete; one inline edit (F22) deferred to chain onto #30's upstream-filing work; Module 10 substrate verified live; calculus-agent on v0.11.1 template parity)

## Where we are

Tutorial content is complete (12 modules + setup + reference) plus the closing **["Where to Go Next"](docs/where-next.md)** page. Module 11's "second LlamaStackDistribution / shadow-route" paragraph was corrected against a real OGX cluster in commit `1f40e27`.

**Phases 1–5 of #28 are done** (this session). State of the original 5-phase plan:

| Phase | Status | Notes |
|---|---|---|
| 0 (llm-d) | done | `findings/00-llm-d-phase0.md` |
| 1 (already-validated guides) | done | byte-for-byte match against live cluster — no drift |
| 2 (setup guides) | done | RHOAI 3.2→3.3 version pin, DSC YAML rewrite, dashboard-via-Gateway-API verify command, helm 4 |
| 3 (Modules 0–9) | done | 5 trivial edits + 1 paragraph rewrite + Module 6 sandbox swap; calculus-agent re-scaffolded from v0.11.1, F9+F10 resolved |
| 4 (Module 10) | done | Substrate gap surfaced + fixed: `configure-shields.md` Wave 2 now enables `responses` API + deps + `default_shield_id`. `/v1/responses` and `/v1/moderations` verified end-to-end. Agent-side claims (`call_model_responses` signature, `PlatformResponse` fields) still need a deployed Module 10 worked example to verify |
| 5 (Module 11) | done (audit) | Cleanest pass — only finding (F22) is a small OpenShift SCC caveat in "Getting started"; deferred to chain onto #30 (file llm-d/llm-d upstream issue first, then update Module 11 to point at the filed issue) |

Per-phase findings under `retrospectives/2026-05-06_tutorial-walkthrough/findings/0[0-5]-*.md`.

## Open issues, in priority order

### 1. [#30 — File upstream issues](https://github.com/fips-agents/examples/issues/30)

Now top of the list — Phase 5's F22 chains onto this work, and the audit pass is otherwise complete. Backlog:

- Original five drafts (against `meta-llama/llama-stack` and `ogx-ai/ogx-k8s-operator`) still pending.
- `findings/upstream-llm-d-doc-drift.md` — README on `main` references guides not present in tag `v0.6.0`.
- `findings/upstream-llm-d-openshift-scc.md` — optimized-baseline manifests CrashLoopBackOff on OpenShift's `restricted-v2` SCC. **Filing this is the F22 dependency** — once landed upstream, point `docs/11-scaling-with-llm-d.md`'s "Getting started" section at the filed issue with a one-paragraph note. F22 detail in `findings/05-phase5-module-11.md`.
- One additional curiosity surfaced in Phase 4 worth confirming/filing: OGX's `code-scanner` shield refusal stringifies the comma-separated `violation_type` character-by-character (`(violation type: e, v, a, l, …)` instead of `(violation type: eval-with-expression, insecure-eval-use)`). Looks like an upstream LlamaStack bug; mentioned in `findings/04-phase4-module-10.md`.

Open question (unchanged): file the llm-d drafts under #30 (broaden its scope) or open a sibling tracking issue specifically for `llm-d/llm-d`?

Filing happens in its own session — research each upstream's CONTRIBUTING / issue-template first. llm-d uses a Bug Report YAML template (no docs template) — the two existing drafts are pre-formatted for it.

### 2. [#29 — Human walkthrough](https://github.com/fips-agents/examples/issues/29)

The audit pass is done; the worked-example gap is closed; the Module 10 substrate is live-verified. #29's clean-room read-through is now genuinely unblocked. Schedule whenever a fresh-eyes session is available; F22's deferral doesn't block (it's a known footgun with a known fix, not a doc-flow problem).

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
| `9a19def` | `docs: Update NEXT_SESSION.md to reflect calculus-agent re-scaffold` |
| `91e19f2` | `docs: Enable Module 10 platform mode in configure-shields Wave 2 (F18, F19, F20, #28 phase 4)` |
| `b127d6b` | `docs: Update NEXT_SESSION.md after Phase 4` |
| `ff87ff1` | `docs: Add Phase 5 retrospective — Module 11 audit (#28)` |

Phase 1 had no doc edits (clean). Phase 2 touched 3 setup guides (`cluster-options`, `install-cli-tools`, `install-openshift-ai`). Phase 3 + follow-ups touched 6 module/page files (`01-scaffold-agent`, `05-gateway-and-ui`, `06-code-sandbox`, `07-extend-with-ai`, `09-file-uploads`, `where-next`). The re-scaffold touched 23 files inside `calculus-agent/`, plus `.gitignore` (the prep that lets `.claude/commands/` actually commit). Phase 4 extended `configure-shields.md`'s Wave 2 ConfigMap (Path A + Path B) and reframed one bullet in `10-guardrails-and-observability.md`; cluster `ogx-config` ConfigMap was rolled to match. Phase 5 added the Module 11 retrospective with no doc-side edits (F22 deferred to chain onto #30).

## Cluster state — `cluster-hpdl7-sandbox2435` (context: `kagenti-memory-hub`)

One mutation this session: Phase 4 extended `ogx-config` to enable platform mode (`/v1/responses` + `/v1/moderations` defaults). OGX rolled, healthy. Everything else untouched.

| Resource | Namespace | Notes |
|---|---|---|
| `InferenceService gpt-oss` | `gpt-oss-model` | `RedHatAI/gpt-oss-20b` on L40S #1 (RHAIIS:3) |
| `InferenceService llama-guard` | `llama-guard-model` | `RedHatAI/Llama-Guard-4-12B-quantized.w8a8` on L40S #2 (`vllm/vllm-openai:v0.20.1`) |
| `LlamaStackDistribution ogx` | `ogx` | Now serves `responses` + `vector_io` + `files` + `file_processors` APIs alongside the original three; `default_shield_id: code-scanner` set. Two providers (`vllm` + `vllm-guard`); shields registered |
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
