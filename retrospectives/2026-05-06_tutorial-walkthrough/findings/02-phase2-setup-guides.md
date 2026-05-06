# Phase 2 — re-verify setup guides not recently validated

**Date:** 2026-05-06
**Cluster:** `cluster-hpdl7-sandbox2435` (context `kagenti-memory-hub`); OCP 4.20.18 + RHOAI 3.3.1
**Targets:** `cluster-options.md`, `install-openshift-ai.md`, `install-cli-tools.md`, `registry-setup.md`, `observability-backends.md`
**Outcome:** 2 guides clean (`registry-setup`, `observability-backends`); 3 guides have drift to file (`cluster-options`, `install-openshift-ai`, `install-cli-tools`). Drift is all in-tutorial — none upstream — so candidates for inline fix.

## observability-backends.md — clean ✅

| Doc claim | Cluster state | Match |
|---|---|---|
| `observability` ns | exists | ✅ |
| Jaeger Deployment, image `jaegertracing/all-in-one:1.76.0` | exact match | ✅ |
| Service ports 16686 / 4317 / 4318 | exact match | ✅ |
| `jaeger-ui` Route, edge | exists, `…apps.cluster-hpdl7…` host resolves | ✅ |
| LSD `containerSpec.command: ["opentelemetry-instrument"]` + `args` (uvicorn factory) | byte-for-byte match | ✅ |
| 4 OTEL_* env vars (endpoint, service name, exporter, protocol) | match | ✅ |
| Traces flow → service `ogx` appears in Jaeger | confirmed via `/api/services` after a chat-completions ping | ✅ |

This guide is the single example in this whole pass that's *exactly* right.

## registry-setup.md — clean (instructions only — not end-to-end re-verified) ✅

The doc describes two paths: Quay.io (Path 1) and the OpenShift internal registry (Path 2). Neither was end-to-end re-verified because:
- Path 1 needs an external Quay account — out of scope for cluster-side checks.
- Path 2's first step (`oc patch configs.imageregistry.operator.openshift.io/cluster --type merge -p '{"spec":{"defaultRoute":true}}'`) hasn't been applied on this cluster (the `default-route` Route doesn't exist), so the rest of Path 2 has nothing to verify against.

The internal image-registry pods are running normally (`image-registry-*`, `node-ca-*`, etc. in `openshift-image-registry`), so the prerequisite for Path 2 holds. Instructions read correctly. No drift to file.

## cluster-options.md — minor drift 🟡

| Line | Doc says | Reality | Severity |
|---|---|---|---|
| 10 | "validated on the 4.20 + RHOAI 3.2 pairing" | cluster is 4.20.18 + RHOAI **3.3.1** | Low — version pin is stale. Tutorial still works on 3.3.1, but the validated-pairing claim should track. |

### F4 — Tutorial pinned to RHOAI 3.2 in prose; channel `fast-3.x` now lands 3.3 (DRAFT)

Two surface areas: `cluster-options.md` line 10 ("validated on 4.20 + RHOAI 3.2") and `install-openshift-ai.md` line 18 ("This tutorial targets Red Hat OpenShift AI 3.2"). Channel name `fast-3.x` is unchanged, but the version it lands moved.

Suggested fix: rephrase to "RHOAI 3.x via the `fast-3.x` channel (validated on 3.3.1)" to avoid pinning to a specific point release that the channel will move past.

## install-openshift-ai.md — significant drift 🟠

This is the heaviest finding in Phase 2. The DSC YAML and verification commands target an older RHOAI 3.x shape; the operator on this cluster is now **3.3.1** with a substantially expanded (and partially renamed) DSC component schema.

### F5 — DSC YAML uses obsolete component names for RHOAI 3.3 (DRAFT)

The doc's example DSC (`docs/guides/install-openshift-ai.md:66–86`):

```yaml
spec:
  components:
    kserve:
      managementState: Managed
      serving:                          # ← removed in 3.3
        managementState: Managed
        name: knative-serving
    dashboard:
      managementState: Managed
    workbenches:
      managementState: Managed
    modelmeshserving:                   # ← not a 3.3 component
      managementState: Removed
    datasciencepipelines:               # ← renamed to aipipelines in 3.3
      managementState: Managed
```

Cluster's actual DSC components list: `aipipelines`, `dashboard`, `feastoperator`, `kserve`, `kueue`, `llamastackoperator`, `mlflowoperator`, `modelregistry`, `ray`, `trainer`, `trainingoperator`, `trustyai`, `workbenches`. The `kserve` block has fields the doc doesn't mention: `nim`, `modelsAsService`, `rawDeploymentServiceConfig: Headless`. The Knative `serving` sub-block is gone (KServe Raw is the default).

Whether the doc's YAML still applies cleanly on 3.3 is undetermined — the operator may silently drop unknown fields on apply, or it may reject. Either way, a fresh reader applying it and then `oc get dsc -o yaml` won't recognize the cluster from the example.

Suggested fix: refresh the example to a minimum-viable 3.3 DSC — keep `kserve.managementState: Managed` (and explicitly note `rawDeploymentServiceConfig: Headless` since the rest of the tutorial leans on Headless behavior), `dashboard: Managed`, `workbenches: Managed`, leave the rest at default. Don't enumerate every component — let the operator's defaults handle them.

### F6 — Dashboard verification command broken on RHOAI 3.3 (DRAFT)

`docs/guides/install-openshift-ai.md:103–106`:

```bash
oc get route -n redhat-ods-applications rhods-dashboard \
  -o jsonpath='{.spec.host}'
```

On 3.3 this returns `Error from server (NotFound): routes.route.openshift.io "rhods-dashboard" not found`. RHOAI 3.3 exposes the dashboard via **Gateway API**, not a plain Route:

- `HTTPRoute rhods-dashboard` in `redhat-ods-applications` (no host of its own)
- `Route data-science-gateway` in `openshift-ingress` (the actual hostname — `data-science-gateway.apps.<cluster-domain>`)
- The `Gateway data-science-gateway` (in `openshift-ingress`, class `data-science-gateway-class`) ties them together

Suggested fix:

```bash
oc get route data-science-gateway -n openshift-ingress \
  -o jsonpath='{.spec.host}'
```

…and add a one-line note that 3.3+ exposes the dashboard through the data-science-gateway, not a Route in `redhat-ods-applications`.

### F7 — Subsumed by F4 (same version-pin issue, different file)

## install-cli-tools.md — minor drift 🟡

| Line | Doc says | Reality | Severity |
|---|---|---|---|
| 76 | "helm 3.x" | brew installs `helm 4.0.4` (released earlier this year) | Low |
| 97 | `pipx install fips-agents-cli` (no version) | local has 0.11.1; tutorial pin in `index.md` is 0.11.0 | Out of scope here (tutorial pin lives in `index.md`, which is correct as-is) |

### F8 — Doc says "helm 3.x" but homebrew now installs helm 4.x (DRAFT)

Helm 4.0 shipped in early 2026 and is now the homebrew default. Helm 4 is mostly backward-compatible for chart consumers (`helm install`, `helm upgrade`, `helm template`) which is all this tutorial uses. The "3.x" pin in the prose is no longer accurate — and would push readers to manually downgrade for no reason.

Suggested fix: drop the "3.x" qualifier; just say "helm". The underlying commands in the tutorial don't depend on a 3.x-specific feature.

## Summary of follow-up findings

| ID | File(s) | Change kind | Effort |
|---|---|---|---|
| F4 | `cluster-options.md`, `install-openshift-ai.md` | Reword version pin (3.2 → "3.x via fast-3.x channel, validated on 3.3.1") | Trivial — two prose edits |
| F5 | `install-openshift-ai.md` | Rewrite DSC YAML for 3.3 component schema | Medium — pick the right minimum-viable DSC, validate on cluster |
| F6 | `install-openshift-ai.md` | Replace dashboard verification command (Gateway API path) | Trivial — one command swap + one-line note |
| F8 | `install-cli-tools.md` | Drop "3.x" qualifier on helm | Trivial — single-word edit |

All four are in-tutorial drift (no upstream filing needed). F4, F6, and F8 are good candidates for a single fix-up commit. F5 needs a moment of judgment about how minimal the example DSC should be.

## Time + cost

- ~25 min wall time, no cluster mutations, no scaling.
- Smoke-test a chat completion through OGX → Jaeger to confirm trace flow (one OGX request, ~5s).
