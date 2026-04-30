# Choosing a Cluster

This tutorial needs an OpenShift 4.14+ cluster where you can install operators
and (ideally) attach a GPU. Several cluster options work — pick the one that
matches your access and budget.

## At a glance

| Option | GPU access | Time to ready | Cost | Path |
|--------|------------|---------------|------|------|
| Self-managed OpenShift | Yes (you provision) | Hours | Hardware/cloud | A |
| ROSA (Red Hat OpenShift on AWS) | Yes (GPU node pool) | ~1 hour | AWS billing | A |
| ARO (Azure Red Hat OpenShift) | Yes (GPU node pool) | ~1 hour | Azure billing | A |
| Local CRC (CodeReady Containers) | No (single-node) | ~30 min | Free | B |
| Red Hat Developer Sandbox | No | Instant | Free | B |

**Path A** = full tutorial experience with on-cluster vLLM.
**Path B** = deploy everything except the LLM; supply an external
OpenAI-compatible endpoint via `MODEL_ENDPOINT`.

## Self-managed OpenShift

Install OpenShift on bare metal, VMware, or any supported platform. You'll
need at least one worker node with a GPU (NVIDIA A10, L4, A100, H100, or
similar — ~24 GB VRAM minimum for Granite 3.3 8B at fp16).

This is the most flexible option but also the most work.

→ [Red Hat OpenShift install documentation](https://docs.redhat.com/en/documentation/openshift_container_platform/latest/html/installing/index)

## ROSA / ARO

Managed OpenShift on AWS or Azure. Add a GPU machine pool after the cluster
comes up. Billing is hourly — remember to scale GPU nodes to zero when not
in use.

→ [ROSA documentation](https://docs.redhat.com/en/documentation/red_hat_openshift_service_on_aws)
→ [ARO documentation](https://docs.redhat.com/en/documentation/azure_red_hat_openshift)

## Local CRC

[CodeReady Containers][crc] runs a single-node OpenShift on your laptop.
There's no GPU, so vLLM serving is not feasible — use Path B.

CRC is fine for working through the agent / MCP server / gateway / UI parts
of the tutorial against a remote LLM endpoint.

[crc]: https://developers.redhat.com/products/openshift-local/overview

## Red Hat Developer Sandbox

The [Developer Sandbox][sandbox] gives you a shared OpenShift environment
with no install required. There are no GPUs and limited resource quotas, but
it's the fastest way to get the agent stack running. Use Path B.

[sandbox]: https://developers.redhat.com/developer-sandbox

## FIPS mode

If you're standing up a fresh cluster and your environment requires (or might
require) FIPS, enable it at install time — FIPS cannot be enabled on an
existing cluster. Every component built in this tutorial works in FIPS mode.

→ [Installing a cluster in FIPS mode](https://docs.redhat.com/en/documentation/openshift_container_platform/latest/html/installing/installing-fips)

## Next

Once you have a cluster: [Install OpenShift AI](install-openshift-ai.md).
