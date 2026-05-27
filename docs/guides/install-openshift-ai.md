# Install OpenShift AI

Red Hat OpenShift AI is the MLOps layer on top of OpenShift. The tutorial uses
it for **KServe-based model serving** (vLLM as the runtime). Other OpenShift AI
components — workbenches, pipelines, distributed training — aren't required
for this tutorial but won't hurt if they're enabled.

!!! note "Path B users"
    If you're running on Developer Sandbox or CRC and using an external LLM
    endpoint, skip this guide. You don't need OpenShift AI installed.

## Prerequisites

- An OpenShift 4.20+ cluster (see [Choosing a Cluster](cluster-options.md))
- `cluster-admin` rights
- `oc` logged in to the cluster

This tutorial targets **Red Hat OpenShift AI 3.x** via the `fast-3.x`
channel (validated on 3.3.1). RHOAI 3.x requires OpenShift 4.19 or later.

!!! tip "RHOAI 3.4 for supplementary modules"
    The core tutorial (Modules 0-11) works on RHOAI 3.3+. The
    [Models as a Service](../supplementary/maas-model-serving.md) and
    [MCP Gateway](../supplementary/mcp-gateway.md) supplementary modules
    require **RHOAI 3.4**, which GA'd on May 14, 2026. If you're on 3.3,
    the `fast-3.x` channel will deliver 3.4 automatically — approve the
    upgrade in OLM when prompted. No operator reinstall is needed.

## Install the operator

From the OpenShift web console:

1. Navigate to **Operators → OperatorHub**.
2. Search for **Red Hat OpenShift AI**.
3. Click the tile, then **Install**.
4. Choose the **`fast-3.x`** channel (3.2 or later).
5. Accept the defaults (installed into `redhat-ods-operator`).

!!! tip "Already have RHOAI on a shared cluster?"
    If Red Hat OpenShift AI is already installed (e.g., by a cluster admin),
    skip the Namespace, OperatorGroup, and Subscription steps below.
    Jump straight to [Create a DataScienceCluster](#create-a-datasciencecluster).

Or from the CLI:

```bash
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: rhods-operator
  namespace: redhat-ods-operator
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: rhods-operator
  namespace: redhat-ods-operator
spec:
  channel: fast-3.x   # stable-3.x also works and is more common in production clusters
  name: rhods-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

Wait until the operator pods are running:

```bash
oc get pods -n redhat-ods-operator -w
```

## Create a DataScienceCluster

The `DataScienceCluster` (DSC) custom resource tells the operator which
components to enable. For this tutorial you need **kserve** managed; leave
the rest at the operator's defaults. Two non-obvious choices below get
inline comments.

```yaml
apiVersion: datasciencecluster.opendatahub.io/v1
kind: DataScienceCluster
metadata:
  name: default-dsc
spec:
  components:
    kserve:
      managementState: Managed
      # The rest of the tutorial assumes KServe Raw with a Headless predictor
      # service — that's what produces the `:8000` URL caveat in serve-an-llm.md
      # and install-ogx.md. RHOAI 3.x defaults to Headless; setting it
      # explicitly documents the dependency.
      rawDeploymentServiceConfig: Headless
    dashboard:
      managementState: Managed
    llamastackoperator:
      # RHOAI 3.x bundles a LlamaStack/OGX operator. We install the upstream
      # ogx-k8s-operator in install-ogx.md instead (the rebrand hasn't shipped
      # via RHOAI yet) — leaving this Removed avoids two operators reconciling
      # the same LlamaStackDistribution.
      managementState: Removed
```

Apply it:

```bash
oc apply -f dsc.yaml
```

## Verify

```bash
oc get dsc default-dsc -o jsonpath='{.status.phase}'
# Ready
```

The Dashboard hostname should also resolve. RHOAI 3.x exposes the
dashboard via Gateway API (not a plain `Route` in `redhat-ods-applications`):

```bash
oc get route data-science-gateway -n openshift-ingress \
  -o jsonpath='{.spec.host}'
```

If `kserve` shows `Ready` in the DSC status, you're done.

## Next

[Serve an LLM](serve-an-llm.md).

## Further reading

- [Red Hat OpenShift AI documentation](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/)
- [Red Hat AI 3 supported product and hardware configurations](https://docs.redhat.com/en/documentation/red_hat_ai/3/html-single/supported_product_and_hardware_configurations/index)
- [Red Hat OpenShift AI supported configurations (3.x)](https://access.redhat.com/articles/rhoai-supported-configs-3.x)
- [Open Data Hub upstream](https://opendatahub.io/)
