# Makefile Targets

Both the agent and MCP server project templates include a `Makefile` that wraps
common development, testing, and deployment commands. Running `make` with no
arguments prints a summary of available targets.

```bash
make        # same as `make help`
make help
```

## Variables

The agent Makefile exposes variables that you can override on the command line.
The MCP server Makefile uses the same convention for `VENV`, `PYTHON`, and
`PROJECT`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `VENV` | `.venv` | Virtual environment directory |
| `PYTHON` | `python3` | Python interpreter used to create the venv |
| `PROJECT` | project-specific | OpenShift namespace for deploy/clean targets |
| `IMAGE_NAME` | project-specific | Container image name (agent only) |
| `IMAGE_TAG` | `latest` | Container image tag (agent only) |

```bash
# Override at invocation
make deploy PROJECT=my-agent IMAGE_TAG=v1.2.0
```

## Development

Targets for setting up a local environment and running the project.

| Target | Description | When to use |
|--------|-------------|-------------|
| `install` | Create a venv and install all dependencies | First time setup, or after changing dependencies |
| `run-local` | Start the project locally | Day-to-day development and manual testing |

=== "Agent"

    ```bash
    make install     # installs dev + memory extras via pip install -e ".[dev,memory]"
    make run-local   # starts the HTTP server on port 8080
    ```

=== "MCP Server"

    ```bash
    make install     # installs from requirements.txt
    make run-local   # starts in STDIO mode with hot-reload enabled
    ```

!!! note "Transport difference"
    The agent runs as an HTTP server by default (`/v1/chat/completions`). The
    MCP server runs in STDIO mode locally for `cmcp` testing and switches to
    HTTP when deployed. See the [MCP Protocol](mcp-protocol.md) reference for
    transport details.

## Testing

| Target | Description | When to use |
|--------|-------------|-------------|
| `test` | Run the pytest suite with verbose output | Before every commit |
| `test-cov` | Run tests with coverage report (term + HTML) | Checking coverage gaps (agent only) |
| `test-local` | Test the MCP server with `cmcp` | Quick smoke test of tool discovery (MCP server only) |
| `eval` | Run eval cases against the agent | After changing agent behavior or prompts (agent only) |
| `lint` | Run ruff on `src/`, `tests/`, `evals/` | Before every commit (agent only) |

```bash
# Agent workflow
make lint
make test
make test-cov     # opens htmlcov/index.html for the coverage report
make eval         # runs evals/evals.yaml with a mock LLM

# MCP server workflow
make test
make test-local   # requires cmcp: pip install cmcp
```

`test-cov` generates both terminal output and an HTML report in `htmlcov/`.
`eval` uses the eval runner at `evals/run_evals.py`, which loads cases from
`evals/evals.yaml` and runs them against the agent with a mock LLM so that
evals are fast and deterministic.

!!! tip "Lint auto-installs"
    The agent `lint` target installs `ruff` into the venv automatically if it
    isn't already present. You don't need to install it separately.

## Container Build

| Target | Description | When to use |
|--------|-------------|-------------|
| `build` | Build a container image with Podman | Before deploying or testing the container locally (agent only) |

```bash
make build
make build IMAGE_NAME=calculus-agent IMAGE_TAG=v1.0.0
```

The target runs `podman build` with `--platform linux/amd64` and `--no-cache`
to produce an image compatible with OpenShift. This target is only present in
the agent Makefile -- the MCP server template uses an OpenShift BuildConfig
instead (see `deploy.sh` in the MCP server project).

!!! warning "Building on macOS"
    Podman on Apple Silicon defaults to ARM64. The `build` target forces
    `linux/amd64` so the image runs on OpenShift, but this means emulated
    builds that are slower than native. For faster iteration, consider using a
    remote x86_64 builder.

## Deployment

| Target | Description | When to use |
|--------|-------------|-------------|
| `deploy` | Deploy to OpenShift | Initial deployment to a namespace |
| `redeploy` | Force-redeploy (fresh image pull + pod restart) | Pushing an updated image under the same tag (agent only) |
| `clean` | Remove resources from OpenShift | Tearing down a deployment |

All three targets require `PROJECT` to identify the OpenShift namespace.

```bash
make deploy PROJECT=calculus-demo
make redeploy PROJECT=calculus-demo
make clean PROJECT=calculus-demo
```

=== "Agent"

    `deploy` calls `deploy.sh`, which applies the Helm chart from `chart/`.
    `redeploy` calls `redeploy.sh`, which patches the deployment to force an
    image pull and rolling restart. `clean` deletes the deployment, service,
    configmap, and route individually.

=== "MCP Server"

    `deploy` calls `deploy.sh`, which applies the OpenShift manifest from
    `openshift.yaml`. `clean` deletes all resources defined in that manifest.
    There is no separate `redeploy` target -- re-run `deploy` instead.

!!! note "`clean` requires PROJECT"
    The agent `clean` target exits with an error if `PROJECT` is not set, as a
    safety measure against accidentally deleting resources from the wrong
    namespace.

## Maintenance

| Target | Description | When to use |
|--------|-------------|-------------|
| `vendor` | Vendor fipsagents source into the project | Switching from PyPI to a local copy of fipsagents (agent only) |
| `update-fipsagents` | Update vendored fipsagents to latest upstream | After a fipsagents release (agent only) |

```bash
make vendor             # initial vendoring
make update-fipsagents  # pull latest changes
```

!!! note "Renamed from `update-framework`"
    The target was renamed from `update-framework` to `update-fipsagents` to
    match the package being updated. The old name is kept as a deprecated
    alias and will be removed in a future release.

These targets call `fips-agents vendor` under the hood. Vendoring copies the
fipsagents source into `src/fipsagents/` so the project has no PyPI dependency
on fipsagents at runtime. This is useful for air-gapped deployments or when you
need to pin a specific fipsagents version.

## Quick reference

All targets in a single table for quick scanning.

| Target | Agent | MCP Server | Summary |
|--------|:-----:|:----------:|---------|
| `help` | yes | yes | Print available targets |
| `install` | yes | yes | Create venv, install dependencies |
| `run-local` | yes | yes | Run locally (HTTP / STDIO) |
| `test` | yes | yes | Run pytest |
| `test-cov` | yes | -- | Tests with coverage |
| `test-local` | -- | yes | Smoke test with cmcp |
| `eval` | yes | -- | Run eval cases |
| `lint` | yes | -- | Lint with ruff |
| `build` | yes | -- | Build container image |
| `deploy` | yes | yes | Deploy to OpenShift |
| `redeploy` | yes | -- | Force-redeploy |
| `clean` | yes | yes | Remove from OpenShift |
| `vendor` | yes | -- | Vendor fipsagents source |
| `update-fipsagents` | yes | -- | Update vendored fipsagents |

The MCP server also defines a `dev` alias that maps to `run-local`.
