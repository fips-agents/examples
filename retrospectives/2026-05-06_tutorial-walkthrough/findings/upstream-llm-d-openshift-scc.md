# Upstream draft: optimized-baseline manifests crash on OpenShift's `restricted-v2` SCC due to unwritable `/.config` and `/.triton`

**Target repo:** `llm-d/llm-d`
**Template:** Bug Report (`.github/ISSUE_TEMPLATE/bug.yml`)
**Filing status:** drafted, **not filed**. To be filed in a future session.
**Working diff in hand:** `retrospectives/2026-05-06_tutorial-walkthrough/manifests/llm-d-modelserver/patch-decode.yaml`

---

## Title

`[Bug :bug:]: optimized-baseline model server CrashLoopBackOff on OpenShift due to unwritable /.config and /.triton`

## Contact Details

(Use the filer's email at filing time.)

## What happened?

Following the README quickstart against an OpenShift 4.20 cluster (RHOAI 3.2 installed) using `vllm/vllm-openai:v0.19.1` (the upstream-pinned image in `guides/optimized-baseline/modelserver/gpu/vllm/kustomization.yaml`), the model server pod CrashLoopBackOffs at engine init. Logs show:

```
(EngineCore pid=84) PermissionError: [Errno 13] Permission denied: '/.config'
...
(EngineCore pid=84) torch._inductor.exc.InductorError: PermissionError: [Errno 13] Permission denied: '/.triton'
(EngineCore pid=84) ERROR ... EngineCore failed to start.
RuntimeError: Engine core initialization failed.
```

Root cause: under OpenShift's default `restricted-v2` SCC, the container runs as an arbitrary high UID (e.g. `1000800000`). The `vllm/vllm-openai` image is built with `/` owned by root, so `os.makedirs('/.config', ...)` and `os.makedirs('/.triton', ...)` both fail.

The upstream overlay already mounts an `emptyDir` at `/.cache` (for `torch.compile`'s cache directory) — this was clearly added with non-root-friendly cache paths in mind. The same fix is needed for `/.config` (used by vllm's `usage_lib._USAGE_STATS_JSON_PATH`) and `/.triton` (Triton compiler cache, fatal — kills engine init).

This is reproducible on any Kubernetes distribution that enforces non-root execution by default. OpenShift is the most prominent example, but plain k8s with PSA `restricted` baseline + a non-root pod security policy hits the same wall.

### Expected behavior

The optimized-baseline overlay should run on OpenShift's default SCC out of the box, since the README is explicit that OpenShift is a supported target ("Nightly - optimized baseline E2E (OpenShift)" CI badge in README).

### Reproduction

```bash
# Cluster: OpenShift 4.20.x, default SCC binding for new pods
git clone https://github.com/llm-d/llm-d.git && cd llm-d
kubectl create namespace llm-d-test
kubectl apply -n llm-d-test -k guides/optimized-baseline/modelserver/gpu/vllm/

# Pod CrashLoopBackOff within ~30 seconds; logs show /.triton PermissionError
kubectl logs -n llm-d-test -l llm-d.ai/role=decode --previous | grep -i Permission
```

### Fix

Two additional `emptyDir` volumes mounted at `/.config` and `/.triton`. Strategic merge patch we used:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: decode
spec:
  template:
    spec:
      containers:
        - name: modelserver
          volumeMounts:
            - mountPath: /.config
              name: vllm-config
            - mountPath: /.triton
              name: triton-cache
      volumes:
        - name: vllm-config
          emptyDir: {}
        - name: triton-cache
          emptyDir: {}
```

After applying this patch, vLLM boots normally and serves requests.

### Question for maintainers

The README has a passing nightly CI badge for OpenShift (`nightly-e2e-optimized-baseline-ocp.yaml`). How does that CI get past these PermissionErrors? Either:

- The CI uses an overlay/patch that isn't in the documented quickstart path
- The CI runs with a less-restricted SCC (e.g. `anyuid`) than the default
- The image being tested in CI differs from `vllm/vllm-openai:v0.19.1`

If the fix is one of these, surfacing it in the optimized-baseline README would close the gap for users who follow the documented path against a default-configured OpenShift cluster.

## Version

`v0.6.0` (the latest tagged release at filing time; the directory layout we hit only exists on `main`, see related issue draft for that)

## Relevant log output

```
(EngineCore pid=84) Exception in thread Thread-1 (_report_usage_worker):
(EngineCore pid=84)   File "/usr/local/lib/python3.12/dist-packages/vllm/usage/usage_lib.py", line 276, in _write_to_file
(EngineCore pid=84)     os.makedirs(os.path.dirname(_USAGE_STATS_JSON_PATH), exist_ok=True)
(EngineCore pid=84) PermissionError: [Errno 13] Permission denied: '/.config'

(EngineCore pid=84) ERROR [core.py:1108] EngineCore failed to start.
(EngineCore pid=84) ERROR ...
(EngineCore pid=84)   File "/usr/local/lib/python3.12/dist-packages/triton/runtime/cache.py", line 55, in __init__
(EngineCore pid=84)     os.makedirs(self.cache_dir, exist_ok=True)
(EngineCore pid=84) torch._inductor.exc.InductorError: PermissionError: [Errno 13] Permission denied: '/.triton'

RuntimeError: Engine core initialization failed. See root cause above.
```

---

## Filing checklist (when this gets filed)

- [ ] Verify the issue still exists at filing time (re-run repro on a fresh OpenShift cluster)
- [ ] Confirm the patch still applies cleanly to the current `main` overlay
- [ ] Cross-link from `fips-agents/examples` Module 11 walkthrough finding
- [ ] If maintainers confirm the CI uses a different overlay, frame this as a "docs/quickstart fix" rather than a "manifest bug"
