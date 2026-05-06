# 11. Scaling Inference with llm-d

Module 10 graduated tool orchestration and safety to a platform layer (OGX). The remaining single point of contention in the architecture is the model server itself — one vLLM `InferenceService` behind OGX, serving every request. That works fine for a tutorial; in production it stops working as soon as you have more concurrent users than that vLLM can keep responsive, or as soon as you want a model larger than fits on a single accelerator.

This chapter is conceptual — there's no agent code change, and no required step. Its job is to show you what fits behind OGX when one vLLM is no longer enough, so you know the next move when you outgrow Module 5's deployment.

## Where the bottleneck lives

LLM inference has two phases with very different resource profiles:

- **Prefill** — the model reads the entire prompt once. Compute-heavy, runs in parallel across all input tokens, releases the GPU when the first output token is ready.
- **Decode** — the model produces output tokens one at a time. Memory-bandwidth-bound, holds the GPU for the duration of the response.

A single vLLM instance handles both on the same GPU. That means a long-prompt request stalls all other decode work behind it; a long-decode request blocks new prefills from starting. Worse, every replica recomputes the prefix cache for similar prompts independently — even when two requests share 90% of their system prompt, two GPUs do the prefill work twice.

Horizontal autoscaling helps but doesn't solve these problems. Adding replicas adds capacity uniformly across both phases, when the actual contention is asymmetric and prefix-cache-shaped.

## What llm-d does about it

[llm-d](https://llm-d.ai) is a Kubernetes-native distributed inference framework built on vLLM. Three of its design choices change the picture:

**Disaggregated prefill and decode.** Prefill workers and decode workers are separate Deployments with separate scaling rules. A prefill spike doesn't starve decoders; a long-decode request doesn't block new prefills.

**KV-cache-aware routing.** A request whose prompt prefix already lives in some worker's cache gets routed to that worker, skipping the prefill recomputation. Hits compound under multi-tenant traffic, where many requests share system prompts, RAG context, or conversation history.

**Hierarchical KV offloading.** Cache that doesn't fit on the GPU spills to host memory and (in v0.5+) further tiers, extending effective context capacity beyond accelerator VRAM.

The architecture surfaces as an OpenAI-compatible HTTP endpoint — the same surface vLLM exposes, so anything that talks to vLLM today can talk to llm-d tomorrow.

## Where it slots in

The agent doesn't move. OGX doesn't even move much. Only the inference provider's URL changes:

```
After Module 10:                       After llm-d:

Agent → OGX ──┬─→ vLLM (single)        Agent → OGX ──┬─→ llm-d gateway
              │                                       │       │
              ├─→ MCP                                 │       ├─→ prefill workers (N)
              │                                       │       │
              └─→ shields                             │       └─→ decode workers (M)
                                                      │
                                                      ├─→ MCP
                                                      │
                                                      └─→ shields
```

Inside the OGX `config.yaml` you authored in [Install OGX](guides/install-ogx.md), the `providers.inference[].config.url` field changes from your vLLM `InferenceService` URL to the llm-d gateway URL. Nothing else in OGX changes. Nothing in the agent changes — it never knew what was behind OGX in the first place. That's the payoff for the platform-layer work in Module 10.

## When to reach for it

llm-d is a meaningful operational lift — multiple Deployments, an inference scheduler, a separate routing layer. Don't deploy it because it sounds interesting. Reach for it when one or more of these is true:

| Signal | Why llm-d helps |
|--------|-----------------|
| Sustained QPS exceeds what a single vLLM keeps responsive | Disaggregated workers + KV-cache routing absorb load that doesn't scale linearly with replicas |
| Many users share long system prompts, RAG context, or conversation history | KV-cache-aware routing turns prefix overlap into actual prefill savings |
| Model size approaches or exceeds single-accelerator VRAM | Hierarchical KV offloading extends effective context beyond GPU memory |
| You're running multiple LoRA adapters | Cache-aware LoRA routing keeps adapter switching cheap |
| Workload is bursty enough that you want scale-to-zero between traffic windows | v0.5+ supports it natively |

If none of these apply yet, a single vLLM behind OGX is the right answer — and llm-d's payoff comes precisely because the rest of your stack doesn't have to know it exists when you do switch.

## Getting started

The llm-d project documents its own quickstart and Kubernetes install. Two pages worth bookmarking:

- [llm-d.ai](https://llm-d.ai) — the project home, with the latest version and architecture overview
- [github.com/llm-d/llm-d](https://github.com/llm-d/llm-d) — source, releases, and the Kubernetes deployment manifests

When you're ready to test it without disturbing your tutorial deployment, point a *second* `LlamaStackDistribution` at the llm-d gateway, register it as a separate `provider_id` in the same OGX `config.yaml`, and shadow-route a percentage of traffic. The platform-mode design from Module 10 makes A/B comparison a config edit, not an architectural change.

## What's next

You've reached the end of the structured tutorial. The patterns you've built up — scaffolding agents with `fips-agents create`, exposing tools via MCP, hardening for production, graduating concerns to the platform — apply to any agent you want to build on Red Hat AI. The reference pages in the sidebar cover the configuration surface in depth when you need it.

If you build something with this stack, file an issue or PR at [fips-agents/examples](https://github.com/fips-agents/examples) — the tutorial improves the most when it bumps into real-world problems we hadn't thought of.
