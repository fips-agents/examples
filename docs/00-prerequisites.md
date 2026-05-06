# Before You Begin

This tutorial deploys real services to a real cluster. Before you start Module 1,
work through this checklist. Each item links to a setup guide if you need help.

!!! tip "Two paths through this tutorial"
    **Path A — Full cluster.** You have an OpenShift cluster with OpenShift AI
    installed and at least one GPU available. You will serve **Granite 3.3 8B
    Instruct** on-cluster with vLLM and route the agent to it. This is the
    intended experience.

    **Path B — External model.** You don't have a cluster, or your cluster has
    no GPUs (e.g., the [Red Hat Developer Sandbox][sandbox]). You will still
    deploy the agent, MCP server, gateway, and UI — but the LLM lives somewhere
    else. Any OpenAI-compatible endpoint works (a hosted vLLM, a corporate
    inference gateway, etc.). Wherever the tutorial says "set `MODEL_ENDPOINT`,"
    point it at your external URL.

    [sandbox]: https://www.redhat.com/en/technologies/cloud-computing/openshift/try-it

## Requirements

### 1. An OpenShift cluster

OpenShift 4.20 or later. You need cluster-admin (or equivalent permission to
install operators and create namespaces).

→ See [Choosing a Cluster](guides/cluster-options.md) for self-managed,
ROSA, Developer Sandbox, and local CRC tradeoffs.

!!! note "FIPS mode is encouraged"
    Every agent and MCP server you build in this tutorial is FIPS-compatible.
    If you're standing up a fresh cluster, consider enabling FIPS at install
    time — it can't be turned on later. See the [Red Hat OpenShift FIPS
    documentation][fips] for instructions.

    [fips]: https://docs.redhat.com/en/documentation/openshift_container_platform/latest/html/installation_overview/installing-fips

### 2. Red Hat OpenShift AI

The **Red Hat OpenShift AI** operator (3.2 or later) must be installed via
the `fast-3.x` channel, and a `DataScienceCluster` provisioned with KServe
enabled for model serving. RHOAI 3.x requires OpenShift 4.20+.

→ See [Install OpenShift AI](guides/install-openshift-ai.md).

### 3. An LLM (RedHatAI/gpt-oss-20b)

The tutorial uses **`RedHatAI/gpt-oss-20b`** served via vLLM. You need:

- An OpenAI-compatible endpoint URL (`MODEL_ENDPOINT`)
- The model identifier (`MODEL_NAME`)

**Path A:** deploy vLLM on your cluster (one ~24 GB GPU; the MXFP4-quantized variant fits in ~16 GB).
**Path B:** use any external OpenAI-compatible URL.

→ See [Serve an LLM](guides/serve-an-llm.md). The Path B fallback is in the
same guide.

### 4. CLI tools

- `oc` (OpenShift client)
- `helm` 3.x
- `pipx`
- Python 3.11 or later
- `fips-agents` CLI (`pipx install fips-agents-cli`)

→ See [Install CLI Tools](guides/install-cli-tools.md).

### 5. A container registry you can push to

Modules 2, 3, and 6 build and push container images. Quay.io (free public
namespaces) works for the tutorial; the OpenShift internal registry works
if you'd rather keep everything in-cluster.

→ See [Registry Setup](guides/registry-setup.md).

## Quick verification

Before starting Module 1, you should be able to run:

```bash
oc whoami                                    # logged into the cluster
oc get dsc                                   # DataScienceCluster exists
curl -s "$MODEL_ENDPOINT/v1/models"          # LLM responds
fips-agents --version                        # CLI installed
helm version --short                         # helm available
```

If any of those fail, fix it before continuing — the tutorial assumes all five
work.

## Ready?

Head to [Module 1: Scaffold Your Agent](01-scaffold-agent.md).
