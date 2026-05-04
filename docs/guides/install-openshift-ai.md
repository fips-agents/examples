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

This tutorial targets **Red Hat OpenShift AI 3.2** (installed via the
`fast-3.x` channel). RHOAI 3.x requires OpenShift 4.19 or later.

## Install the operator

From the OpenShift web console:

1. Navigate to **Operators → OperatorHub**.
2. Search for **Red Hat OpenShift AI**.
3. Click the tile, then **Install**.
4. Choose the **`fast-3.x`** channel (3.2 or later).
5. Accept the defaults (installed into `redhat-ods-operator`).

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
  channel: fast-3.x
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
components to enable. For this tutorial you need **kserve** managed; the
others can stay at their defaults.

```yaml
apiVersion: datasciencecluster.opendatahub.io/v1
kind: DataScienceCluster
metadata:
  name: default-dsc
spec:
  components:
    kserve:
      managementState: Managed
      serving:
        managementState: Managed
        name: knative-serving
    dashboard:
      managementState: Managed
    workbenches:
      managementState: Managed
    modelmeshserving:
      managementState: Removed
    datasciencepipelines:
      managementState: Managed
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

The Dashboard route should also resolve:

```bash
oc get route -n redhat-ods-applications rhods-dashboard \
  -o jsonpath='{.spec.host}'
```

If `kserve` shows `Ready` in the DSC status, you're done.

## Next

[Serve an LLM](serve-an-llm.md).

## Further reading

- [Red Hat OpenShift AI 3.2 documentation](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.2)
- [Red Hat AI 3 supported product and hardware configurations](https://docs.redhat.com/en/documentation/red_hat_ai/3/html-single/supported_product_and_hardware_configurations/index)
- [Red Hat OpenShift AI supported configurations (3.x)](https://access.redhat.com/articles/rhoai-supported-configs-3.x)
- [Open Data Hub upstream](https://opendatahub.io/)
