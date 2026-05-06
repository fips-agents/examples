# 6. Code Execution Sandbox

Your agent solves calculus problems symbolically, and users can reach it
through the chat UI you deployed in Module 5. But what if someone asks
"evaluate that integral from 0 to 1 and give me a decimal answer"? Or
"generate a table of values for this function"? Symbolic tools alone can't do
this. In this module, you'll deploy a secure code execution sandbox as a
sidecar container and give the agent a new tool that lets it write and run
Python code.

## What the sandbox does

The sandbox is a lightweight HTTP service that accepts Python code, executes it
in a restricted environment, and returns stdout, stderr, and the result. It runs
as a **sidecar container** in the same pod as your agent, communicating over
localhost.

This gives the LLM the ability to write arbitrary Python for numerical
computation, data transformation, and analysis. The agent decides when to use
it -- the `code_executor` tool has `llm_only` visibility, so the LLM calls it
directly when it determines that running code is the best approach.

The obvious concern: running LLM-generated code is dangerous. The sandbox
addresses this with defense in depth.

## Security architecture

The sandbox enforces four independent security layers. An attacker would need to
bypass all of them to do anything harmful.

| Layer | Mechanism | What it blocks |
|-------|-----------|---------------|
| **AST analysis** | Parses code into an abstract syntax tree before execution | Dangerous patterns: `exec()`, `eval()`, `__import__()`, attribute access to `__subclasses__`, `__globals__`, etc. |
| **Import hook** | Custom import system with an explicit allowlist | Any module not in the active profile's allowlist -- `os`, `subprocess`, `socket`, `shutil`, `ctypes`, etc. |
| **Landlock** | Linux security module restricting filesystem access | All filesystem reads/writes outside `/tmp/sandbox` |
| **Resource limits** | Container-level CPU and memory constraints | Resource exhaustion (infinite loops, memory bombs) |

The sandbox container also has **no outbound network access**. Even if code
somehow bypasses the import hook, it cannot reach external services.

!!! note "Landlock requires Linux 5.13+"
    Landlock is a Linux kernel feature. It is active in the OpenShift pod but
    may not be available when running locally on macOS. The other three layers
    still protect you, and container resource limits remain your primary
    defense against resource exhaustion.

## Build the sandbox image

Scaffold a sandbox project the same way you scaffolded the agent, MCP
server, gateway, and UI, then build the image into your `calculus-agent`
namespace via BuildConfig:

```bash
fips-agents create sandbox code-sandbox --local --yes
cd code-sandbox

oc new-build --binary --name=code-sandbox --strategy=docker \
  -n calculus-agent --context="$CTX"
oc patch bc/code-sandbox --type=json \
  -p '[{"op":"replace","path":"/spec/strategy/dockerStrategy/dockerfilePath","value":"Containerfile"}]' \
  -n calculus-agent --context="$CTX"
oc start-build code-sandbox --from-dir=. --follow \
  -n calculus-agent --context="$CTX"
```

The scaffold produces the same project as
[fips-agents/code-sandbox](https://github.com/fips-agents/code-sandbox)
upstream — same FastAPI sidecar, same `/execute` shape, same four
security layers. If you'd rather clone the repo directly (e.g., to track
upstream security fixes with `git pull`), `gh repo clone fips-agents/code-sandbox && cd code-sandbox`
works identically from this point.

The build takes 2–3 minutes and pushes
`image-registry.openshift-image-registry.svc:5000/calculus-agent/code-sandbox:latest`
to the cluster's internal registry.

## Enable the sandbox in your Helm chart

The sandbox is configured as an optional sidecar in the agent's Helm chart.
Open `chart/values.yaml` and add the `sandbox` section, pointing
`image.repository` at the image stream you just built:

```yaml
sandbox:
  enabled: true
  image:
    repository: image-registry.openshift-image-registry.svc:5000/calculus-agent/code-sandbox
    tag: latest
  resources:
    limits:
      cpu: 500m
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 128Mi
```

When `sandbox.enabled` is `true`, the Helm chart does two things:

1. Adds a second container to the pod spec running the sandbox image
2. Sets the `SANDBOX_URL=http://localhost:8000` environment variable in the
   agent container's ConfigMap

The sidecar shares the pod's network namespace, so the agent reaches it at
`localhost:8000` with no Service or Route required.

Deploy the updated chart:

```bash
helm upgrade calculus-agent chart/ \
  --set sandbox.enabled=true \
  --reuse-values \
  -n calculus-agent
```

Verify the pod now has two containers:

```bash
oc get pods -n calculus-agent -l app.kubernetes.io/instance=calculus-agent
```

```
NAME                              READY   STATUS    RESTARTS   AGE
calculus-agent-7b4f9d8c6-x2k1p   2/2     Running   0          30s
```

The `2/2` in the READY column confirms both the agent and the sandbox sidecar
are running.

## Add the code_executor tool

Create `tools/code_executor.py` in your agent project. This is a **local tool**
(not an MCP tool) that POSTs code to the sandbox and returns the output.

```python
import os
import httpx
from fipsagents.baseagent.tools import tool

SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://localhost:8000")


@tool(
    description=(
        "Execute Python code in a secure sandbox. Use this for numerical "
        "computation, data analysis, building tables, or any task that "
        "benefits from running code. Returns stdout and the expression result."
    ),
    visibility="llm_only",
)
async def code_executor(code: str) -> str:
    """Execute Python code and return the output.

    Args:
        code: Python source code to execute. The sandbox has access to
              math, statistics, numpy, and other data-science libraries
              depending on the active profile.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{SANDBOX_URL}/execute",
            json={"code": code},
        )

    if response.status_code != 200:
        return f"Sandbox error (HTTP {response.status_code}): {response.text}"

    result = response.json()
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("result") is not None:
        parts.append(f"Result: {result['result']}")
    if result.get("stderr"):
        parts.append(f"Stderr: {result['stderr']}")
    if result.get("error"):
        parts.append(f"Error: {result['error']}")

    return "\n".join(parts) if parts else "(no output)"
```

The tool is deliberately simple: send code, return output. All security
enforcement happens inside the sandbox -- the tool itself is just an HTTP
client.

!!! tip "Local development"
    For local development without OpenShift, start the sandbox manually:

    ```bash
    cd sandbox && uvicorn sandbox.app:app --port 8000
    ```

    Then set the environment variable before starting your agent:

    ```bash
    export SANDBOX_URL=http://localhost:8000
    make run-local
    ```

## Update the system prompt

The LLM needs to know it can execute code. Open `prompts/system.md` and add a
section describing the capability:

```markdown
## Code Execution

You have access to a Python sandbox via the `code_executor` tool. Use it when:

- The user asks for a numerical (decimal) answer to a symbolic result
- You need to evaluate an expression at specific values
- You need to generate a table of data points
- The task involves computation that is easier to express as code

The sandbox has access to the Python standard library and, depending on the
profile, NumPy and SciPy. Write clean, self-contained Python scripts. Print
results with `print()` -- the last expression's value is also captured.

Do NOT use the sandbox for tasks that the symbolic MCP tools handle directly
(integration, differentiation, limits, etc.). Use symbolic tools first, then
the sandbox for numerical follow-up.
```

This instruction guides the LLM to use the right tool for the right task:
symbolic MCP tools for exact math, the sandbox for numerical computation.

## Rebuild and redeploy

You've added a new file (`tools/code_executor.py`) and updated the system
prompt, so the agent image needs to be rebuilt:

```bash
oc start-build calculus-agent --from-dir=. --follow -n calculus-agent
oc rollout restart deployment/calculus-agent -n calculus-agent
oc rollout status deployment/calculus-agent -n calculus-agent
```

Verify the agent discovered the new local tool alongside the MCP tools:

```bash
ROUTE=$(oc get route calculus-agent -n calculus-agent -o jsonpath='{.spec.host}')

curl -sk "https://$ROUTE/v1/agent-info" | python -m json.tool
```

```json
{
    "tools": [
        "integrate",
        "differentiate",
        "code_executor"
    ]
}
```

The two MCP tools come from the calculus-helper server; `code_executor` is the
local tool you just added.

## Test it

Try these prompts through the chat UI or curl.

**Numerical evaluation:**

```
Integrate sin(x) from 0 to pi and give me the decimal value.
```

The agent should use the `integrate` MCP tool first (getting the symbolic
result `2`), then optionally use the sandbox to confirm numerically:

```python
import scipy.integrate
import math

result, _ = scipy.integrate.quad(math.sin, 0, math.pi)
print(f"{result:.10f}")
```

**Data table:**

```
Generate a table showing x, sin(x), and cos(x) for x from 0 to 2*pi in steps of pi/6.
```

The agent writes code using `math` (or `numpy` if the data-science profile is
active) and prints a formatted table.

**Combining symbolic and numerical:**

```
Find the derivative of x^3 * sin(x), then evaluate it at x = 0.1, 0.5, 1.0, and 2.0.
```

The agent uses the `differentiate` MCP tool for the symbolic derivative, then
the sandbox to evaluate the expression at each point and format the results.

## Security walkthrough

Understanding what the sandbox blocks is as important as knowing what it allows.

The cleanest way to exercise the sandbox's defenses is to talk to it directly,
bypassing the LLM. A well-aligned model asked to run `os.system("ls /")` may
just refuse or describe the code instead of executing it -- which tells you
nothing about whether the sandbox works. Hitting the sandbox over HTTP
guarantees the request reaches the security layers.

In one terminal, forward the sandbox port out of the pod:

```bash
oc port-forward -n calculus-agent \
  deployment/calculus-agent 8000:8000
```

In a second terminal, POST code to `/execute`. Each example below is a
self-contained `curl` you can run directly.

### Blocked: dangerous imports

```bash
curl -s localhost:8000/execute \
  -H 'content-type: application/json' \
  -d '{"code": "import os\nos.system(\"ls /\")"}' \
  | python -m json.tool
```

Response:

```json
{
    "error": "Import 'os' is not allowed in the current security profile. Allowed modules: math, statistics, itertools, functools, re, datetime, collections, json, csv, string, textwrap, decimal, fractions, random, operator, typing"
}
```

The same happens for `subprocess`, `socket`, `shutil`, `ctypes`, `importlib`,
and any other module not on the allowlist.

### Blocked: code analysis patterns

```bash
curl -s localhost:8000/execute \
  -H 'content-type: application/json' \
  -d '{"code": "\"\".__class__.__bases__[0].__subclasses__()"}' \
  | python -m json.tool
```

Response:

```json
{
    "error": "Code analysis blocked: access to '__subclasses__' is not permitted."
}
```

The AST analyzer catches attribute access to dunder methods commonly used in
sandbox escape techniques.

### Blocked: resource exhaustion

```bash
curl -s localhost:8000/execute \
  -H 'content-type: application/json' \
  -d '{"code": "x = [0] * (10**9)"}' \
  | python -m json.tool
```

The container's memory limit terminates the process before it can allocate
gigabytes of memory. The response contains a timeout or OOM error rather than
the allocated list.

!!! tip "Optional: confirm the kill from the cluster side"
    Unlike the import and AST cases -- where the sandbox itself produces the
    error message -- resource exhaustion is enforced by the container runtime,
    so the `curl` response may be terse. To see *why* the process died, check
    the sandbox container's logs and the namespace's events:

    ```bash
    oc logs -n calculus-agent deployment/calculus-agent -c sandbox --tail=20
    oc get events -n calculus-agent --field-selector reason=OOMKilling
    ```

When you're done testing, stop the `oc port-forward` process with Ctrl-C.

## Profiles

Profiles control which modules are available in the sandbox. The sandbox
accepts a `profile` field in the request body.

| Profile | Available modules |
|---------|-------------------|
| `minimal` | math, statistics, itertools, functools, re, datetime, collections, json, csv, string, textwrap, decimal, fractions, random, operator, typing |
| `data-science` | Everything in `minimal` plus numpy, pandas, scipy (when installed in the sandbox image) |

The `code_executor` tool uses the default profile configured on the sandbox.
To use a specific profile, extend the tool to pass a `profile` parameter:

```python
response = await client.post(
    f"{SANDBOX_URL}/execute",
    json={"code": code, "profile": "data-science"},
)
```

!!! warning "Profile availability depends on the sandbox image"
    The `data-science` profile only works if the sandbox image includes numpy,
    pandas, and scipy. The base `code-sandbox:latest` image
    includes them. If you build a custom sandbox image, install the packages you
    need.

### Exercise: create a visualization profile

As a practice exercise, think through what a `visualization` profile would look
like. It would extend the `data-science` profile with `matplotlib`. Consider:

- Which additional modules need to be allowlisted? (`matplotlib`,
  `matplotlib.pyplot`, possibly `PIL` for image handling)
- How would the sandbox return an image? (Base64-encoded PNG in the response
  JSON, or write to a shared volume)
- What new security concerns does rendering introduce? (matplotlib can read
  fonts from the filesystem, generate arbitrary SVG, etc.)

This is a design exercise -- you don't need to implement it to continue the
tutorial.

## Composable capabilities

Step back and look at what your agent can do now:

| Capability | Provided by | Strength |
|------------|------------|----------|
| Symbolic math | MCP server (SymPy tools) | Exact results: integrals, derivatives, limits, series |
| Numerical computation | Sandbox (Python execution) | Decimal evaluation, tables, iterative algorithms |
| Reasoning | LLM | Deciding which approach to use, explaining results |

The key insight is **composability**. The symbolic tools and the sandbox serve
different purposes, and the LLM orchestrates between them. A single question
like "integrate this function and plot it from 0 to 10" naturally decomposes
into a symbolic step (get the antiderivative) and a numerical step (evaluate
and format the output). Neither tool alone can handle both, but together they
cover the full workflow.

This pattern -- specialized MCP tools for domain operations, plus a general
sandbox for computation -- scales beyond calculus. The same architecture works
for any domain where you need both structured tool calls and freeform code
execution.

## What's next

Your agent now has symbolic tools, code execution, and a chat UI. In
[Module 7](07-extend-with-ai.md), you'll use AI-assisted slash commands to add
new capabilities without writing boilerplate by hand.
