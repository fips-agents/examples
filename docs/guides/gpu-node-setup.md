# GPU Node Setup

This guide provisions a GPU-enabled worker node on an AWS-based OpenShift
cluster. The GPU node is required for on-cluster model serving (Path A in
[Serve an LLM](serve-an-llm.md)) and for the
[Models as a Service](../supplementary/maas-model-serving.md) supplementary
module.

The process installs two operators (Node Feature Discovery and NVIDIA GPU
Operator), creates a GPU-capable MachineSet, and applies the NVIDIA
ClusterPolicy that configures drivers and device plugins.

!!! info "Prerequisites"
    - OpenShift 4.20+ on AWS
    - `cluster-admin` access
    - `oc` logged in to the cluster
    - Budget for a GPU instance (~$1.60/hr for `g6e.4xlarge`)

!!! tip "Multi-cluster safety"
    Every `oc` command in this guide includes `--context="$CTX"` to avoid
    targeting the wrong cluster. Set it once per shell session:

    ```bash
    export CTX=$(oc config current-context)
    ```

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
oc apply --context="$CTX" -f nfd-subscription.yaml
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

```bash
# Wait for the InstallPlan to appear
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

## Step 3: Create a GPU MachineSet

OpenShift manages worker nodes through MachineSets. Rather than writing one
from scratch, clone an existing worker MachineSet and modify it for GPU use.

The script below exports the first worker MachineSet, changes the instance
type to `g6e.4xlarge` (1 NVIDIA L40S, 48 GB VRAM), increases the disk to
200 GB, adds the `nvidia.com/gpu` taint, and sets replicas to 1:

```bash
# Clone an existing worker MachineSet for GPU
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

!!! warning "Node provisioning takes ~15 minutes"
    AWS needs time to launch the instance, and the GPU Operator needs time to
    install drivers on the new node. Watch progress:

    ```bash
    oc get machines --context="$CTX" -n openshift-machine-api -w
    ```

    The Machine will progress through `Provisioning` → `Provisioned` →
    `Running`. Once it's `Running`, wait for the corresponding Node to become
    `Ready`:

    ```bash
    oc get nodes --context="$CTX" -w
    ```

!!! tip "Instance type alternatives"
    `g6e.4xlarge` provides an L40S with 48 GB VRAM at ~$1.60/hr. If your
    region doesn't have `g6e` availability, `g5.4xlarge` (A10G, 24 GB VRAM,
    ~$1.20/hr) also works for tutorial-sized models. Adjust `instanceType` in
    the `jq` command above.

## Step 4: Apply the ClusterPolicy

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
      schedule onto nodes with the `nvidia.com/gpu` taint from Step 3.

```bash
oc apply --context="$CTX" -f cluster-policy.yaml
```

Wait for the ClusterPolicy to reach `ready` state. This can take several
minutes as the operator builds and loads driver containers:

```bash
oc get clusterpolicy gpu-cluster-policy --context="$CTX" \
  -o jsonpath='{.status.state}{"\n"}' -w
```

## Step 5: Verify GPU availability

Once the ClusterPolicy is ready and the node is `Ready`, confirm that the
GPU is visible to Kubernetes:

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

## (Optional) Create a Hardware Profile

If you use the RHOAI dashboard to deploy models, a HardwareProfile makes
GPU resources selectable in the UI. This step is optional if you only deploy
models via CLI manifests.

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
