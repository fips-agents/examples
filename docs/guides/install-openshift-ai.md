# Install OpenShift AI and GPU Support

This guide installs the platform stack: **Red Hat OpenShift AI** for model
serving, plus **GPU infrastructure** for on-cluster inference. Installing the
GPU operators before RHOAI produces more reliable results because NFD labels
are already present when the DataScienceCluster reconciles.

!!! note "Path B users"
    If you're running on Developer Sandbox or CRC and using an external LLM
    endpoint, skip this guide. You don't need OpenShift AI or GPU operators
    installed.

## Prerequisites

- OpenShift 4.20+ on AWS (see [Choosing a Cluster](cluster-options.md))
- `cluster-admin` rights
- `oc` logged in to the cluster
- Budget for a GPU instance (approximately $1.60/hr for `g6e.4xlarge` at time of writing)

This tutorial targets **Red Hat OpenShift AI 3.x** via the `fast-3.x`
channel (validated on 3.3.1). RHOAI 3.x requires OpenShift 4.19 or later.

!!! tip "RHOAI 3.4 for supplementary modules"
    The core tutorial (Modules 0-11) works on RHOAI 3.3+. The
    [Models as a Service](../supplementary/maas-model-serving.md) and
    [MCP Gateway](../supplementary/mcp-gateway.md) supplementary modules
    require **RHOAI 3.4**, which GA'd on May 14, 2026. If you're on 3.3,
    the `fast-3.x` channel will deliver 3.4 automatically — approve the
    upgrade in OLM when prompted. No operator reinstall is needed.

!!! tip "Multi-cluster safety"
    Every `oc` command in this guide includes `--context="$CTX"` to avoid
    targeting the wrong cluster. Set it once per shell session:

    ```bash
    export CTX=$(oc config current-context)
    ```

---

## Get the manifests

The YAML manifests used in this guide live in the repo under `manifests/platform/`.
Clone the repo if you haven't already:

```bash
git clone https://github.com/fips-agents/examples.git
cd examples/manifests/platform
```

Each step below also shows the YAML inline for reference, so you can review
what each manifest contains before applying it.

---

## Step 1: Install Node Feature Discovery (NFD)

NFD detects hardware features on each node — including GPUs — and exposes
them as Kubernetes labels. The NVIDIA GPU Operator depends on these labels,
so NFD must be installed first.

Create the namespace, then apply the OperatorGroup and Subscription:

```bash
oc create namespace openshift-nfd --context="$CTX" --dry-run=client -o yaml \
  | oc apply --context="$CTX" -f -
```

```yaml
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-nfd-group
  namespace: openshift-nfd
spec:
  targetNamespaces:
    - openshift-nfd
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: nfd
  namespace: openshift-nfd
spec:
  channel: stable
  installPlanApproval: Automatic
  name: nfd
  source: redhat-operators
  sourceNamespace: openshift-marketplace
```

```bash
oc apply --context="$CTX" -f nfd-operatorgroup-subscription.yaml
```

Wait for the operator to install:

```bash
oc get csv --context="$CTX" -n openshift-nfd -w
```

Once the CSV phase shows `Succeeded`, create the NFD instance operand.
This tells the operator to start scanning nodes:

```yaml
apiVersion: nfd.openshift.io/v1
kind: NodeFeatureDiscovery
metadata:
  name: nfd-instance
  namespace: openshift-nfd
spec:
  workerConfig:
    configData: |
      core:
        sleepInterval: 60s
```

```bash
oc apply --context="$CTX" -f nfd-instance.yaml
```

## Step 2: Install the NVIDIA GPU Operator

Create the namespace:

```bash
oc create namespace nvidia-gpu-operator --context="$CTX" --dry-run=client -o yaml \
  | oc apply --context="$CTX" -f -
```

Apply the OperatorGroup and Subscription. The GPU Operator uses **Manual**
install plan approval so you control exactly which version lands on the
cluster:

```yaml
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: nvidia-gpu-operator-group
  namespace: nvidia-gpu-operator
spec:
  targetNamespaces:
    - nvidia-gpu-operator
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: gpu-operator-certified
  namespace: nvidia-gpu-operator
spec:
  channel: v25.3
  installPlanApproval: Manual
  name: gpu-operator-certified
  source: certified-operators
  sourceNamespace: openshift-marketplace
```

```bash
oc apply --context="$CTX" -f gpu-operator-subscription.yaml
```

Because `installPlanApproval` is `Manual`, you need to find and approve the
InstallPlan:

Wait for the InstallPlan to appear:

```bash
oc get installplan --context="$CTX" -n nvidia-gpu-operator -w
```

Once it appears with `APPROVED=false`, approve it:

```bash
INSTALL_PLAN=$(oc get installplan --context="$CTX" -n nvidia-gpu-operator \
  -o jsonpath='{.items[?(@.spec.approved==false)].metadata.name}')

oc patch installplan "$INSTALL_PLAN" --context="$CTX" -n nvidia-gpu-operator \
  --type merge -p '{"spec": {"approved": true}}'
```

Wait for the CSV to succeed:

```bash
oc get csv --context="$CTX" -n nvidia-gpu-operator -w
```

## Step 3: Install Red Hat OpenShift AI

!!! tip "Already have RHOAI on a shared cluster?"
    If Red Hat OpenShift AI is already installed (e.g., by a cluster admin),
    skip the Namespace, OperatorGroup, and Subscription steps below.
    Jump straight to [Create a DataScienceCluster](#step-5-create-a-datasciencecluster).

From the OpenShift web console:

1. Navigate to **Operators -> OperatorHub**.
2. Search for **Red Hat OpenShift AI**.
3. Click the tile, then **Install**.
4. Choose the **`fast-3.x`** channel (3.2 or later).
5. Accept the defaults (installed into `redhat-ods-operator`).

Or from the CLI — create the namespace first, then apply the OperatorGroup
and Subscription:

```bash
oc create namespace redhat-ods-operator --context="$CTX" \
  --dry-run=client -o yaml | oc apply --context="$CTX" -f -

oc apply --context="$CTX" -n redhat-ods-operator -f - <<EOF
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
oc get pods --context="$CTX" -n redhat-ods-operator -w
```

## Step 4: Create a GPU MachineSet

OpenShift manages worker nodes through MachineSets. Rather than writing one
from scratch, clone an existing worker MachineSet and modify it for GPU use.

The script below exports the first worker MachineSet, changes the instance
type to `g6e.4xlarge` (1 NVIDIA L40S, 48 GB VRAM), increases the disk to
200 GB, adds the `nvidia.com/gpu` taint, and sets replicas to 1:

Clone an existing worker MachineSet for GPU:

```bash
WORKER_MS=$(oc get machineset --context="$CTX" -n openshift-machine-api \
  -o jsonpath='{.items[0].metadata.name}')

oc get machineset "$WORKER_MS" --context="$CTX" -n openshift-machine-api -o json | \
  jq --arg name "gpu-${WORKER_MS}" '
    .metadata.name = $name |
    .metadata.resourceVersion = null |
    .metadata.uid = null |
    .metadata.creationTimestamp = null |
    .spec.replicas = 1 |
    .spec.selector.matchLabels["machine.openshift.io/cluster-api-machineset"] = $name |
    .spec.template.metadata.labels["machine.openshift.io/cluster-api-machineset"] = $name |
    .spec.template.spec.providerSpec.value.instanceType = "g6e.4xlarge" |
    .spec.template.spec.providerSpec.value.blockDevices[0].ebs.volumeSize = 200 |
    .spec.template.spec.taints = [{"key": "nvidia.com/gpu", "value": "", "effect": "NoSchedule"}]
  ' | oc apply --context="$CTX" -f -
```

!!! tip "Parallel work"
    Steps 4 and 5 can run in parallel — the GPU MachineSet provisions while
    the DataScienceCluster reconciles. Both take a few minutes.

!!! warning "Node provisioning takes ~15 minutes"
    AWS needs time to launch the instance, and the GPU Operator needs time to
    install drivers on the new node. Watch progress:

    ```bash
    oc get machines --context="$CTX" -n openshift-machine-api -w
    ```

    The Machine will progress through `Provisioning` -> `Provisioned` ->
    `Running`. Once it's `Running`, wait for the corresponding Node to become
    `Ready`:

    ```bash
    oc get nodes --context="$CTX" \
      -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,GPU:.status.capacity."nvidia\.com/gpu" -w
    ```

!!! tip "Instance type alternatives"
    `g6e.4xlarge` provides an L40S with 48 GB VRAM (approximately $1.60/hr
    at time of writing). If your region doesn't have `g6e` availability,
    `g5.4xlarge` (A10G, 24 GB VRAM, approximately $1.20/hr at time of
    writing) also works for tutorial-sized models. Adjust `instanceType` in
    the `jq` command above. Check current AWS pricing for your region and
    account agreement.

## Step 5: Create a DataScienceCluster

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
    modelregistry:
      managementState: Managed
      registriesNamespace: rhoai-model-registries
    llamastackoperator:
      # RHOAI 3.x bundles a LlamaStack/OGX operator. We install the upstream
      # ogx-k8s-operator in install-ogx.md instead (the rebrand hasn't shipped
      # via RHOAI yet) — leaving this Removed avoids two operators reconciling
      # the same LlamaStackDistribution.
      managementState: Removed
```

!!! info "Model registry"
    Enabling `modelregistry` makes the Red Hat AI model catalog available in
    the RHOAI dashboard under **AI hub**, so you can browse and deploy models
    from the UI.

Apply it:

```bash
oc apply --context="$CTX" -f dsc.yaml
```

!!! warning "Wait for GPU node readiness"
    If you started Steps 4 and 5 in parallel, pause here until your GPU
    node is fully ready. The ClusterPolicy's driver daemonsets need a GPU
    node to schedule on. Confirm the node is `Ready` and reporting GPU
    capacity:

    ```bash
    oc get nodes --context="$CTX" \
      -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,GPU:.status.capacity."nvidia\.com/gpu"
    ```

    You should see one node with `1` in the GPU column before proceeding.

## Step 6: Apply the NVIDIA ClusterPolicy

The NVIDIA ClusterPolicy tells the GPU Operator how to configure drivers,
device plugins, and monitoring on GPU nodes. Apply it after the operator is
installed:

```yaml
apiVersion: nvidia.com/v1
kind: ClusterPolicy
metadata:
  name: gpu-cluster-policy
spec:
  operator:
    defaultRuntime: crio
    use_ocp_driver_toolkit: true
  driver:
    enabled: true
    upgradePolicy:
      autoUpgrade: true
      maxParallelUpgrades: 1
      maxUnavailable: 25%
  devicePlugin:
    enabled: true
  dcgm:
    enabled: true
  dcgmExporter:
    enabled: true
    serviceMonitor:
      enabled: true
  gfd:
    enabled: true
  migManager:
    enabled: true
    config:
      default: all-disabled
  nodeStatusExporter:
    enabled: true
  toolkit:
    enabled: true
  validator:
    plugin:
      env:
        - name: WITH_WORKLOAD
          value: "false"
  daemonsets:
    tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
    updateStrategy: RollingUpdate
    rollingUpdate:
      maxUnavailable: "1"
```

!!! info "Key settings"
    - `use_ocp_driver_toolkit: true` — uses the OpenShift Driver Toolkit to
      build driver containers matched to your cluster's kernel version.
    - `serviceMonitor: enabled: true` — exposes GPU metrics (utilization,
      temperature, memory) to OpenShift's built-in Prometheus stack.
    - The `daemonsets.tolerations` block ensures GPU Operator pods can
      schedule onto nodes with the `nvidia.com/gpu` taint from Step 4.

```bash
oc apply --context="$CTX" -f cluster-policy.yaml
```

Wait for the ClusterPolicy to reach `ready` state. This can take several
minutes as the operator builds and loads driver containers:

```bash
oc get clusterpolicy gpu-cluster-policy --context="$CTX" \
  -o jsonpath='{.status.state}{"\n"}' -w
```

!!! note
    The ClusterPolicy status may briefly show `notReady` while driver
    daemonsets initialize on the GPU node. This is normal — wait for it to
    settle to `ready`.

## Step 7: Verify

Check that the DataScienceCluster is ready:

```bash
oc get dsc default-dsc --context="$CTX" -o jsonpath='{.status.phase}'
```

The output should show `Ready`.

The Dashboard hostname should also resolve. RHOAI 3.x exposes the
dashboard via Gateway API (not a plain `Route` in `redhat-ods-applications`):

```bash
oc get route data-science-gateway --context="$CTX" -n openshift-ingress \
  -o jsonpath='{.spec.host}'
```

Confirm the GPU is visible to Kubernetes:

```bash
oc get nodes --context="$CTX" \
  -o custom-columns=NAME:.metadata.name,GPU:.status.capacity."nvidia\.com/gpu"
```

You should see one node reporting a GPU capacity of `1`. If the GPU column
shows `<none>` for all nodes, the driver pods may still be initializing.
Check their status:

```bash
oc get pods --context="$CTX" -n nvidia-gpu-operator
```

All pods should be `Running` or `Completed`. If any are stuck in
`CrashLoopBackOff`, check their logs for driver compatibility issues.

If `kserve` shows `Ready` in the DSC status and a GPU node reports capacity,
you're done.

## Step 8: Create a Hardware Profile

A HardwareProfile makes GPU resources selectable in the RHOAI dashboard when
deploying models. Before applying the manifest, open the RHOAI dashboard and
navigate to **Settings > Hardware profiles**. Note the default profile that
is already listed. Then apply the manifest and refresh the page to see the
new NVIDIA GPU profile appear.

```yaml
apiVersion: infrastructure.opendatahub.io/v1
kind: HardwareProfile
metadata:
  name: nvidia-gpu
  namespace: redhat-ods-applications
  labels:
    app.kubernetes.io/part-of: hardwareprofile
    app.opendatahub.io/hardwareprofile: "true"
  annotations:
    opendatahub.io/display-name: "NVIDIA GPU"
    opendatahub.io/description: "NVIDIA GPU accelerator for AI/ML workloads"
    opendatahub.io/disabled: "false"
spec:
  identifiers:
    - displayName: CPU
      identifier: cpu
      defaultCount: 2
      maxCount: 8
      minCount: 1
      resourceType: CPU
    - displayName: Memory
      identifier: memory
      defaultCount: 8Gi
      maxCount: 32Gi
      minCount: 2Gi
      resourceType: Memory
    - displayName: GPU
      identifier: nvidia.com/gpu
      defaultCount: 1
      maxCount: 1
      minCount: 1
      resourceType: Accelerator
  scheduling:
    type: Node
    node:
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

```bash
oc apply --context="$CTX" -f hardware-profile.yaml
```

The profile will appear under **Settings > Hardware profiles** in the RHOAI
dashboard.

## Next

[Serve an LLM](serve-an-llm.md).

## Further reading

- [Red Hat OpenShift AI documentation](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/)
- [Red Hat AI 3 supported product and hardware configurations](https://docs.redhat.com/en/documentation/red_hat_ai/3/html-single/supported_product_and_hardware_configurations/index)
- [Red Hat OpenShift AI supported configurations (3.x)](https://access.redhat.com/articles/rhoai-supported-configs-3.x)
- [Open Data Hub upstream](https://opendatahub.io/)
- [NVIDIA GPU Operator on OpenShift](https://docs.nvidia.com/datacenter/cloud-native/openshift/latest/index.html)
