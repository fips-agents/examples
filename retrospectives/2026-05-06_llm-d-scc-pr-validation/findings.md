# llm-d/llm-d#1430 fix validation — pre-PR cluster proof

**Date:** 2026-05-06
**Cluster:** mcp-rhoai (`api-cluster-n7pd5-...sandbox5167...`); OpenShift 4.x with default `restricted-v2` SCC binding
**Target upstream:** `llm-d/llm-d` issue [#1430](https://github.com/llm-d/llm-d/issues/1430), maintainer-invited PR
**Goal:** prove that adding `/.triton` and `/.config` emptyDir mounts to `guides/optimized-baseline/modelserver/gpu/vllm/patch-vllm.yaml` fixes the OpenShift CrashLoopBackOff before opening the PR.

## Test setup

- **Namespace:** `llm-d-scc-test` (uid-range `1001410000/10000` per default SCC — exactly the high-UID arbitrary-user shape that triggers the bug)
- **GPU node:** new g6e.12xlarge added by scaling `eval-gpu-cluster` 1→2; provides 4 fresh L40S, isolated from cluster's other model-serving workloads
- **Image:** `docker.io/vllm/vllm-openai:v0.19.1` (the upstream-pinned version in `patch-vllm.yaml`)
- **Model:** `Qwen/Qwen3-30B-A3B-Instruct-2507` (MoE, 30B params with 3B active, ~60GB at bf16, fits comfortably on 2× L40S at TP=2)
- **Tensor parallelism:** TP=2 (matches upstream `patch-vllm.yaml` default)
- **HF cache:** PVC `hf-cache` (100Gi gp3-csi) shared between negative + positive tests, so model downloads once

Manifests in `manifests/`:
- `00-pvc.yaml` — shared HF cache
- `01-unpatched.yaml` — replicates upstream `patch-vllm.yaml` mount set: `/dev/shm`, `/.cache`. Missing `/.triton` and `/.config`.
- `02-patched.yaml` — adds `/.triton` (triton-cache emptyDir) and `/.config` (vllm-config emptyDir). This is the proposed PR diff applied to a standalone Deployment.

## Test 1 — Negative control (unpatched)

Applied `manifests/01-unpatched.yaml` — the upstream-shipped mount set (`/dev/shm` + `/.cache`), missing `/.triton` and `/.config`.

**Result: CrashLoopBackOff (7 restarts in 30 minutes), exactly reproducing issue #1430.**

The pod went through:

1. Scheduled to `ip-10-0-10-193` (the new g6e.12xlarge node added by the scale-up)
2. Image pull: 1m47s for `docker.io/vllm/vllm-openai:v0.19.1` (~22 GB)
3. Model download from Hugging Face into the PVC-backed `/cache/hf` (one-time; subsequent restarts re-used it)
4. Engine init started → both PermissionErrors fired

**Two distinct PermissionErrors confirmed**, in chronological order (full log: `test1-unpatched-crashloop.log`):

```
# Line 48 — non-fatal, fires during model loading, allows shard loading to continue
(Worker_TP0 pid=209) PermissionError: [Errno 13] Permission denied: '/.config'

# Line 250 — fatal, fires during torch.compile / Triton kernel compilation
(Worker_TP0 pid=209) ERROR ... torch._inductor.exc.InductorError: PermissionError: [Errno 13] Permission denied: '/.triton'
```

The fatal `/.triton` error path matches the issue body's stack trace exactly:

```
triton/runtime/cache.py:55  os.makedirs(self.cache_dir, exist_ok=True)
triton/runtime/build.py:78  compile_module_from_src
torch/utils/_triton.py:200  triton_hash_with_backend
torch/_inductor/codegen/triton.py:5097  inductor_meta_common
```

Engine init fails → `RuntimeError: Worker failed with error 'PermissionError: [Errno 13] Permission denied: '/.triton''` → pod restarts → CrashLoopBackOff.

The namespace's UID range (`1001410000/10000`) confirmed via `oc get namespace` is exactly the high-UID arbitrary-user pattern that surfaces this bug. No SCC override was applied.

## Test 2 — Positive (patched)

Applied `manifests/02-patched.yaml` — same as Test 1 plus the proposed PR change: emptyDir volumes mounted at `/.triton` and `/.config`.

**Result: pod boots cleanly past the previously-failing point.**

The `/.triton` and `/.config` PermissionErrors are gone (`grep -iE "Permission denied|/.triton|/.config"` over the patched-pod logs returns zero hits — see `test2-patched-startup.log`).

The patched pod first hit a *different*, unrelated failure during KV cache sizing:

```
ValueError: To serve at least one request with the models's max seq len (262144),
(12.0 GiB KV cache is needed, which is larger than the available KV cache memory (10.59 GiB).
Based on the available memory, the estimated maximum model length is 231328.
Try increasing `gpu_memory_utilization` or decreasing `max_model_len` when initializing the engine.
```

This is a model-config issue specific to our test setup: Qwen3-30B-A3B-Instruct-2507's full 262144-token context doesn't fit alongside the model weights on 2× L40S (96 GB total). The maintainer's CI uses Qwen3-32B (32k context) and doesn't hit this.

The crucial point for the PR: this failure is *downstream* of where the SCC bug used to kill the pod. The pod successfully completed:
- Engine init
- Worker process startup (TP=2, both workers up)
- Triton kernel compilation (the path that wrote to `/.triton` and crashed in Test 1)
- Model weight loading from PVC
- The `_report_usage_worker` path that wrote to `/.config` and logged a PermissionError in Test 1

…all paths that depend on `/.triton` and `/.config` being writable. The SCC patch is verified.

To get a fully serving pod, redeployed with `--max-model-len=32768` added to the args. Pod reached Ready 1/1 in ~7 minutes (image cached + model cached on the PVC from Test 1, so this was just engine init + warmup) and stayed up clean: 21 minutes Running, 0 restarts at evidence-capture time.

## Test 3 — Serving smoke

`oc port-forward` into the patched pod, hit `/v1/models` and `/v1/chat/completions`:

```
$ curl http://localhost:18000/v1/models | jq '.data[].id'
"Qwen/Qwen3-30B-A3B-Instruct-2507"

$ curl http://localhost:18000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
         "messages": [{"role": "user", "content": "In one short sentence, say hello and confirm you are running."}],
         "max_tokens": 100}' | jq
{
  "content": "Hello! Yes, I'm running and ready to help.",
  "finish": "stop",
  "usage": {"prompt_tokens": 21, "total_tokens": 34, "completion_tokens": 13}
}
```

vLLM serving end-to-end on OpenShift `restricted-v2` SCC, with the proposed PR mount additions and no other workarounds.

## Teardown

- `oc delete namespace llm-d-scc-test` — deletion cascades to the Deployment + the PVC + its bound 100 GiB EBS volume
- `oc scale machineset eval-gpu-cluster-n7pd5-7kws6-worker-us-east-2a --replicas=1` — controller terminates the added g6e.12xlarge node
- `/tmp/llm-d-scc/` working directory removed
- Cluster restored to pre-validation state (5 GPU nodes, 7 GPUs in use across the existing model-serving deployments)

## Conclusion

The proposed two-line addition to `guides/optimized-baseline/modelserver/gpu/vllm/patch-vllm.yaml` (mounting emptyDir volumes at `/.triton` and `/.config`) fixes the OpenShift `restricted-v2` SCC bug from issue #1430. Verified end-to-end with a real workload (Qwen3-30B-A3B MoE on 2× L40S, TP=2): the unpatched manifest CrashLoopBackOffs with the exact PermissionError stack trace from the issue body; the patched manifest boots cleanly and serves chat completions.

The `/.config` mount is non-fatal but recommended in the same PR for parity with the existing `/.cache` precedent — it eliminates a real PermissionError logged from the `_report_usage_worker` thread on every pod start.
