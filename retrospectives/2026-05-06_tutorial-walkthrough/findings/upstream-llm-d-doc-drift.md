# Upstream draft: llm-d README on `main` describes guides not present in tag v0.6.0

**Target repo:** `llm-d/llm-d`
**Template:** Bug Report (`.github/ISSUE_TEMPLATE/bug.yml` — closest fit; no docs template exists)
**Filing status:** **filed 2026-05-06 as [llm-d/llm-d#1429](https://github.com/llm-d/llm-d/issues/1429).**
**Filing notes:** The `triage` label specified by the bug.yml template doesn't exist on the repo as a defined label — `gh issue create --label triage` errored. Filed with `--label bug` only; maintainers will apply triage labels.

---

## Title

`[Bug :bug:]: README quickstart references guides/optimized-baseline/, but that path doesn't exist in tag v0.6.0`

## Contact Details

(Use the filer's email at filing time.)

## What happened?

The repo `README.md` on the default branch (`main`) documents a quickstart that begins with:

```bash
export branch="main"  # branch, tag, or commit hash
git clone https://github.com/llm-d/llm-d.git && cd llm-d && git checkout ${branch}
```

…and later runs:

```bash
helm install ${GUIDE_NAME} \
    oci://registry.k8s.io/gateway-api-inference-extension/charts/standalone \
    -f guides/recipes/scheduler/base.values.yaml \
    -f guides/optimized-baseline/scheduler/optimized-baseline.values.yaml \
    -n ${NAMESPACE} --version ${GAIE_VERSION}
```

A reasonable reading of "branch, tag, or commit hash" is to substitute the latest **tagged release** (currently `v0.6.0`, published 2026-04-03). Doing so produces a clone in which neither `guides/optimized-baseline/` nor `guides/recipes/scheduler/` exists:

```bash
$ git clone --depth 1 --branch v0.6.0 https://github.com/llm-d/llm-d.git
$ ls guides/
asynchronous-processing/   benchmark/   inference-scheduling/
pd-disaggregation/         precise-prefix-cache-aware/
predicted-latency-based-scheduling/   prereq/   recipes/
simulated-accelerators/   tiered-prefix-cache/   wide-ep-lws/
workload-autoscaling/
$ ls guides/optimized-baseline/
ls: cannot access 'guides/optimized-baseline/': No such file or directory
```

The `optimized-baseline` directory was added on `main` after the `v0.6.0` cut. The README quickstart only works when `branch=main`, which the README implies but does not state. A user pinning to the latest tagged release for reproducibility hits "No such file or directory" at the `helm -f ...` step.

### Expected behavior

One of:

1. **Pin the README example to a specific commit or tag** that contains the referenced paths, instead of letting `branch=main` be the implied default.
2. **State explicitly that the quickstart targets `main`** and that older tagged releases use a different directory structure (e.g. `inference-scheduling` instead of `optimized-baseline`).
3. **Backport the `optimized-baseline` reorganization to a tag** so following the README against the latest release works.

### Reproduction

```bash
git clone --depth 1 --branch v0.6.0 https://github.com/llm-d/llm-d.git
cd llm-d
ls guides/optimized-baseline/scheduler/optimized-baseline.values.yaml
# ls: cannot access ...: No such file or directory
```

### Workaround used

Pinned to a `main`-branch commit SHA (`bbf2654c780b63e105c03408822ed9bcc694bca2` as of 2026-05-06) for our own validation. This is what we'd recommend the README do explicitly.

## Version

`v0.6.0`

## Relevant log output

```
$ helm install quickstart \
    oci://registry.k8s.io/gateway-api-inference-extension/charts/standalone \
    -f guides/recipes/scheduler/base.values.yaml \
    -f guides/optimized-baseline/scheduler/optimized-baseline.values.yaml \
    -n llm-d-quickstart --version v1.5.0

Error: open guides/recipes/scheduler/base.values.yaml: no such file or directory
```

---

## Why this is worth filing

- It's a five-minute fix for the maintainer (one README edit) that saves every new user from a confusing failure on the canonical "Get Started Now" path.
- Rules-of-the-room note: llm-d's CONTRIBUTING.md asks for "clear description of the bug, how to reproduce, and how the change is made." Reproduction is a single `git clone --branch v0.6.0` + `ls`. The remediation options are listed above; the maintainer picks.
- This is not a feature request and does not need a project proposal under their `docs/proposals/` flow.

## Filing checklist (when this gets filed)

- [ ] Verify the drift still exists at filing time (latest tag may have advanced)
- [ ] Update the commit SHA in "Workaround used" to whatever `main` is pointing at on filing day
- [ ] Use the Bug Report template; pre-fill Version dropdown to whatever the latest tag is
- [ ] Cross-link from `fips-agents/examples` Module 11 walkthrough finding
