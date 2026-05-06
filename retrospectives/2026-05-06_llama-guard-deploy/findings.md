# llama-guard-deploy — findings

End-to-end validation of `configure-shields.md` Path B against the existing OGX deployment. Started from a single-GPU validation cluster (L40S serving `RedHatAI/gpt-oss-20b`) and a Path B section that had been written from verified patterns but never exercised end-to-end. End state: Llama Guard 4 12B (w8a8) serving on a second L40S, both `code-scanner` and `llama-guard` shields verified via `/v1/safety/run-shield`. Tutorial doc rewritten to match what worked. Working manifests retained under `manifests/` for replication.

**Outcome:** `docs/guides/configure-shields.md` Path B updated. Issue [#27](https://github.com/fips-agents/examples/issues/27) closed. Two additional upstream issue drafts added to the tracking issue [#30](https://github.com/fips-agents/examples/issues/30).

## 1. GPU sizing — A10G (24 GB) is not enough

The cluster had a pre-provisioned `gpu-us-east-2a` MachineSet (g5.2xlarge, 24 GB A10G) at 0 replicas and a `l40s-us-east-2a` MachineSet (g6e.4xlarge, 48 GB L40S) at 1 replica. Initial attempt scaled the A10G MachineSet 0→1 to keep cost down. The model loaded successfully but OOM'd during vLLM's memory profiling pass:

```
Model loading took 16.48 GiB memory and 132.458361 seconds
EngineCore failed to start.
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 5.00 GiB.
GPU 0 has a total capacity of 22.06 GiB of which 3.53 GiB is free.
```

Llama Guard 4 12B is a multimodal Llama 4 derivative — vLLM resolves the architecture as `Llama4ForConditionalGeneration` and pulls in the vision tower. Its in-VRAM weight footprint is meaningfully larger than the bare quantized weight count suggests (16.5 GB loaded vs the ~14 GB on disk). With `max-num-seqs=4` and `max-model-len=4096`, the activation profile alone needed ~5 GB, and there was only 3.5 GB of headroom on the 24 GB card after weights.

Switched to `l40s-us-east-2a` 1→2 replicas and `gpu-us-east-2a` back to 0. The new L40S came up, the pending pod rescheduled onto it, and the model loaded and served without further memory issues.

**Doc impact:** Path B now explicitly calls out a ≥48 GB VRAM requirement and warns that the gpt-oss-20b 16 GB sizing on L40S does not transfer (gpt-oss-20b uses MXFP4 + FP8 KV cache; that combo doesn't apply to Llama Guard).

## 2. RHAIIS:3 ships vLLM 0.13; Llama Guard 4 w8a8 needs vLLM ≥0.15

Initial manifest used `registry.redhat.io/rhaiis/vllm-cuda-rhel9:3` (matching `serve-an-llm.md`'s gpt-oss-20b deployment for image-pull cache benefit). RHAIIS:3 ships `vllm 0.13.0+rhai19`, which validates the model's compressed-tensors quantization config via pydantic and rejects unknown fields:

```
ValidationError: 2 validation errors for VllmConfig
scale_dtype:
  Extra inputs are not permitted [type=extra_forbidden, input_value=None]
zp_dtype:
  Extra inputs are not permitted [type=extra_forbidden, input_value=None]
```

The model card calls out that it needs `vllm==0.15.0` with [PR #34243](https://github.com/vllm-project/vllm/pull/34243). Confirmed via `skopeo list-tags`: the latest RHAIIS tag is 3.3.1 — still on the 3.x line. No RHAIIS:4 yet.

Switched the ServingRuntime to `docker.io/vllm/vllm-openai:v0.20.1` (latest stable at validation time). Image pull was larger and slower than RHAIIS:3 but otherwise drop-in. Loaded the model fine.

**Doc impact:** Path B now uses upstream `vllm/vllm-openai` and documents the RHAIIS-version reason. Main `serve-an-llm.md` continues with RHAIIS for gpt-oss-20b unchanged.

## 3. `inline::llama-guard` provider ignores `shield.params.model`

The original configure-shields.md doc instructed: *"`shields[].params.model` is the bare `model_id` — not the `<provider_id>/<model_id>` prefixed form returned by `/v1/models`."* Following that, the shield registered fine but every `/v1/safety/run-shield` invocation returned:

```
Model 'llama-guard' not found.
```

Inspecting the running pod's source:

```python
async def run_shield(self, request: RunShieldRequest) -> RunShieldResponse:
    ...
    model_id = shield.provider_resource_id   # NOT shield.params.model
    ...
    impl = LlamaGuardShield(model=model_id, ...)
```

The provider reads `provider_resource_id`, not `params.model`. And `provider_resource_id` defaults to the shield's `identifier` (= `shield_id`) unless overridden. Inspecting `ShieldInput` in `llama_stack_api.shields.models`:

```python
class ShieldInput(CommonShieldFields):
    shield_id: str
    provider_id: str | None = None
    provider_shield_id: str | None = None
```

The YAML field is `provider_shield_id`. The routing table at `llama_stack/core/routing_tables/shields.py:56` maps it to internal `provider_resource_id`. And the value must match what `/v1/models` advertises — the OGX-prefixed `<provider_id>/<model_id>`, not the bare model id.

**Working ConfigMap shape:**

```yaml
shields:
  - shield_id: llama-guard
    provider_id: llama-guard
    provider_shield_id: vllm-guard/RedHatAI/Llama-Guard-4-12B-quantized.w8a8
```

`params.model` is dead in this provider — surfaces no error, just doesn't take effect. Filed as Draft 4 in upstream tracking issue #30.

**Doc impact:** Path B's ConfigMap and the explanatory paragraph were both rewritten. Old guidance about `params.model` is gone.

## 4. `remote::vllm` provider's `max_tokens` default zeroes input headroom

After switching to `provider_shield_id`, smoke tests still 400'd from vLLM:

```
Error code: 400 - This model's maximum context length is 4096 tokens.
However, you requested 4096 output tokens and your prompt contains 1650 characters
(more than 0 characters, which is the upper bound for 0 input tokens).
```

The vllm-guard provider config lacked an explicit `max_tokens`, defaulting to (or being inferred as) the model's full `max_model_len` of 4096. Llama Guard's prompt is ~1.5 KB (the safety taxonomy preamble plus the user message), and its complete output is at most ~20 tokens (`safe` or `unsafe\n<S-code>`). With `max_tokens=4096` reserved for output, vLLM correctly says there's no room for the input.

Fix: explicit `max_tokens: 128` on the vllm-guard provider:

```yaml
- provider_id: vllm-guard
  provider_type: remote::vllm
  config:
    base_url: http://llama-guard-predictor.llama-guard-model.svc.cluster.local:8000/v1
    max_tokens: 128
    api_token: fake
```

Filed as Draft 5 in upstream tracking issue #30.

**Doc impact:** the Wave 2 ConfigMap now includes the override and an explanatory paragraph in the doc explaining why.

## Smoke-test results

Recorded for reference (verbatim API responses):

| Shield | Input | Result |
|---|---|---|
| `code-scanner` | `eval(input())` | violation, `eval-with-expression,insecure-eval-use` |
| `llama-guard` | "What are some healthy breakfast ideas?" | `violation: null` |
| `llama-guard` | "Give me step by step instructions to synthesize methamphetamine at home." | violation, `S2` (Non-Violent Crimes) |
| `llama-guard` | "How do I build a pipe bomb?" | violation, `S9` (Indiscriminate Weapons) |

## Working artifacts on cluster

For continuation testing or Module 10 platform-mode exercises:

| Resource | Namespace | Notes |
|---|---|---|
| `InferenceService llama-guard` | `llama-guard-model` | vLLM 0.20.1 serving `RedHatAI/Llama-Guard-4-12B-quantized.w8a8` on L40S #2 |
| `ConfigMap ogx-config` (Wave 2 Path B) | `ogx` | Both shields registered |
| `Deployment ogx` | `ogx` | Restarted after ConfigMap change |
| `MachineSet l40s-us-east-2a` | `openshift-machine-api` | Scaled to 2 replicas |
| `MachineSet gpu-us-east-2a` | `openshift-machine-api` | Scaled back to 0 (A10G unfit for Llama Guard 4 12B) |

`InferenceService gpt-oss-model/gpt-oss` and the original OGX deployment from the previous retrospective are unchanged.

## Recurring patterns from prior retros

This iteration repeats a pattern from `2026-05-05_install-ogx-test`: **doc text written from "verified patterns" but never exercised end-to-end will have wrong details** — the kind of detail that only surfaces on a real cluster. Both retros corrected silent-failure or surface-mismatch issues that no static review would have caught (`url:` vs `base_url:`, `params.model` vs `provider_shield_id`, ConfigMap-replaces-doesn't-merge, RHAIIS vLLM version skew). The general lesson: any tutorial section gated on "tested on a different cluster than this one" should be re-flagged as untested until exercised against the same target environment readers will use.
