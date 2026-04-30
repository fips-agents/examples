# Registry Setup

Modules 2, 3, and 6 build container images locally and push them to a
registry that the cluster can pull from. Two paths work:

- **Quay.io** (recommended for getting started — free public namespaces)
- **OpenShift internal registry** (everything stays in-cluster)

## Path 1: Quay.io

### 1. Create an account

Sign up at [quay.io](https://quay.io). You get a personal namespace matching
your username (e.g., `quay.io/yourname/...`).

### 2. Create a robot account

Robot accounts are non-interactive credentials used by build tooling.

1. From your Quay user/org page, go to **Robot Accounts → Create Robot Account**.
2. Name it (e.g., `tutorial-pusher`).
3. Grant **Write** access to the repos you'll push to (or to the whole
   namespace).
4. Click the robot's name → **Kubernetes Secret** → copy the YAML or download
   it.

### 3. Log in locally

```bash
podman login quay.io
# Username: yourname+tutorial-pusher
# Password: <robot token>
```

### 4. Create a pull secret in OpenShift

Apply the secret to the namespace where the agent runs (the tutorial uses
`calculus-agent`):

```bash
oc create secret docker-registry quay-pull-secret \
  --docker-server=quay.io \
  --docker-username='yourname+tutorial-pusher' \
  --docker-password='<robot-token>' \
  -n calculus-agent

oc secrets link default quay-pull-secret --for=pull -n calculus-agent
```

Repeat for any other namespace that needs to pull from your Quay namespace
(e.g., `calculus-mcp`).

If your repos are public, you can skip the pull-secret step entirely.

## Path 2: OpenShift internal registry

The internal registry is built into OpenShift and avoids external network
hops. It's a good fit if your cluster has external image-pulling restricted
or you want to keep everything in-cluster.

### 1. Expose the registry route (one-time, cluster-admin)

```bash
oc patch configs.imageregistry.operator.openshift.io/cluster \
  --type merge \
  -p '{"spec":{"defaultRoute":true}}'
```

### 2. Get the route hostname

```bash
HOST=$(oc get route default-route -n openshift-image-registry \
  -o jsonpath='{.spec.host}')
echo "$HOST"
```

### 3. Log in

```bash
podman login -u $(oc whoami) -p $(oc whoami -t) "$HOST"
```

### 4. Push using the OpenShift-native image path

When building, tag with the internal registry path:

```bash
podman build --platform linux/amd64 \
  -t "$HOST/calculus-agent/calculus-agent:latest" \
  -f Containerfile .

podman push "$HOST/calculus-agent/calculus-agent:latest"
```

In-cluster pulls don't need a pull secret — OpenShift handles auth via
ServiceAccount tokens automatically when both push and pull happen on the
same cluster.

## Quick test

Build and push a tiny test image, then pull-check from the cluster:

```bash
podman build -t <registry>/<namespace>/test:1 -f - . <<EOF
FROM registry.access.redhat.com/ubi9/ubi-minimal
CMD ["echo", "ok"]
EOF

podman push <registry>/<namespace>/test:1

oc run pull-test --image=<registry>/<namespace>/test:1 --restart=Never -n <namespace>
oc logs pull-test -n <namespace>     # should print "ok"
oc delete pod pull-test -n <namespace>
```

## Next

You're done with setup. Head back to
[Before You Begin](../00-prerequisites.md) for the final verification, or
jump straight to [Module 1: Scaffold Your Agent](../01-scaffold-agent.md).
