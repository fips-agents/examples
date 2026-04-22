# 3. Build an MCP Server

Your agent is running in OpenShift, but it has no real tools. In this module
you'll build an MCP server that exposes calculus operations -- integration and
differentiation -- as tools any MCP client can call. By the end, the server
will be deployed and testable via the streamable-http protocol.

## Scaffold the MCP server

```bash
fips-agents create mcp-server calculus-helper --local
cd calculus-helper
```

The generated project follows a convention-over-configuration pattern:

| Path | Purpose |
|------|---------|
| `src/main.py` | Entry point -- creates and runs the server |
| `src/core/server.py` | Server bootstrap: providers, middleware, auth |
| `src/tools/` | Tool implementations, auto-discovered at startup |
| `src/resources/` | Resource implementations (empty for this project) |
| `src/prompts/` | Prompt implementations (empty for this project) |
| `Containerfile` | Red Hat UBI build for OpenShift |
| `openshift.yaml` | BuildConfig, Deployment, Service, Route |
| `deploy.sh` | One-command deploy script |

### How auto-discovery works

The server bootstrap in `src/core/server.py` creates `FileSystemProvider`
instances that scan directories for decorated functions:

```python
from fastmcp.server.providers import FileSystemProvider

providers = [
    FileSystemProvider(SRC_ROOT / "tools", reload=hot_reload),
    FileSystemProvider(SRC_ROOT / "resources", reload=hot_reload),
    FileSystemProvider(SRC_ROOT / "prompts", reload=hot_reload),
]
mcp = FastMCP(name, providers=providers, middleware=middleware)
```

Drop a file with a `@tool`-decorated function into `src/tools/`, and the server
picks it up automatically. No registration code, no imports to maintain.

!!! tip "Standalone decorators"
    FastMCP 3.x uses standalone decorators (`from fastmcp.tools import tool`)
    rather than a shared server instance. Tools never import an `mcp` object.
    This is what makes auto-discovery possible -- each file is self-contained.

The entry point (`src/main.py`) is minimal -- it calls `create_server()` then
`run_server(mcp)`. Transport selection (STDIO vs HTTP) is controlled by
environment variables. Locally you use STDIO; the Containerfile sets
`MCP_TRANSPORT=http` for OpenShift.

## Build the shared parsing layer

Before writing tools, create `src/calc.py` -- a shared module for expression
parsing and result formatting. It lives outside `src/tools/` so the
auto-discovery scanner doesn't try to find tool decorators in it.

### The safe namespace

The core idea is a **whitelist** of names available inside parsed expressions.
Anything not in this dict -- `eval`, `__import__`, file I/O -- is inaccessible:

```python
_SAFE_NAMESPACE: dict[str, Any] = {
    "pi": sp.pi, "E": sp.E, "oo": sp.oo,
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "exp": sp.exp, "log": sp.log, "ln": sp.log,
    "sqrt": sp.sqrt, "abs": sp.Abs,
    # ... full list in calculus-helper/src/calc.py
}
```

!!! warning "Why not just `sympify`?"
    SymPy's `sympify()` calls Python's `eval()` internally -- arbitrary code
    execution. The whitelist namespace restricts parsing to mathematical
    functions only. Critical for any MCP server accepting user-supplied
    expressions.

### parse_expression

Wraps SymPy's parser with the safe namespace and coaching-style error messages:

```python
def parse_expression(expr_str: str, *, context: str = "expression") -> sp.Expr:
    stripped = expr_str.strip()
    if not stripped:
        raise ToolError(f"{context} cannot be empty.")

    if "^" in stripped:
        raise ToolError(
            f"Invalid {context}: '{stripped}'. Use '**' for exponents, not '^'. "
            "In Python/SymPy '^' is bitwise XOR (e.g. 2^3 = 1, not 8)."
        )

    try:
        return parse_expr(stripped, local_dict=dict(_SAFE_NAMESPACE),
                          transformations=_TRANSFORMATIONS)
    except (SyntaxError, TokenError, ValueError, TypeError, NameError) as e:
        raise ToolError(f"Could not parse {context}: '{stripped}'. "
                        f"Parser said: {type(e).__name__}: {e}.")
```

The `context` parameter labels which input field failed (e.g. "integrand",
"lower bound"), so the calling agent knows exactly which argument to fix.

### format_result

Every tool returns the same output shape -- a dict with `result`, `latex`,
`is_exact`, and `assumptions`:

```python
def format_result(expr, *, assumptions=None, extra=None) -> dict[str, Any]:
    sympy_expr = expr if isinstance(expr, sp.Basic) else sp.sympify(expr)
    out = {
        "result": str(sympy_expr),
        "latex": sp.latex(sympy_expr),
        "is_exact": not sympy_expr.has(sp.Float),
        "assumptions": list(assumptions or []),
    }
    if extra:
        out.update(extra)
    return out
```

!!! info "Consistent output shapes"
    Returning the same dict from every tool means the consuming agent can use a
    single parsing strategy for all calculus results. The `assumptions` list
    surfaces things like "integration constant omitted" that help the agent
    explain results accurately.

## Add the integrate tool

Create `src/tools/integrate.py`. This is the primary walkthrough --
`differentiate.py` follows the same pattern.

```python
from typing import Annotated
import sympy as sp
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from pydantic import Field
from src.calc import format_result, parse_expression, parse_symbol

@tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def integrate(
    expression: Annotated[str, Field(description=(
        "The integrand in Python/SymPy syntax. Use '**' not '^' for exponents."))],
    variable: Annotated[str, Field(description="Variable of integration, e.g. 'x'.")],
    lower_bound: Annotated[str | None, Field(description=(
        "Lower limit. Use '-oo' for minus infinity. "
        "Must be provided with upper_bound, or omitted for indefinite."))] = None,
    upper_bound: Annotated[str | None, Field(description=(
        "Upper limit. Use 'oo' for plus infinity."))] = None,
    numerical: Annotated[bool, Field(description=(
        "If true, compute numerically. Requires both bounds."))] = False,
    ctx: Context = None,
) -> dict:
    """Compute indefinite or definite integrals with numerical fallback."""
    if ctx is not None:
        await ctx.info(f"integrate: expression={expression!r} variable={variable!r}")

    has_lower, has_upper = lower_bound is not None, upper_bound is not None
    if has_lower != has_upper:
        raise ToolError("Definite integral requires both bounds, or omit both.")
    definite = has_lower and has_upper
    if numerical and not definite:
        raise ToolError("Numerical integration requires both bounds.")

    expr = parse_expression(expression, context="expression")
    sym = parse_symbol(variable, context="variable")
    assumptions: list[str] = []

    if not definite:
        result = sp.integrate(expr, sym)
        assumptions.append("integration constant omitted")
        return format_result(result, assumptions=assumptions)

    low = parse_expression(lower_bound, context="lower bound")
    high = parse_expression(upper_bound, context="upper bound")

    if numerical:
        return format_result(sp.Integral(expr, (sym, low, high)).evalf(),
                             assumptions=assumptions)

    result = sp.integrate(expr, (sym, low, high))
    if isinstance(result, sp.Integral):
        return format_result(result.evalf(), assumptions=assumptions)
    if result in (sp.oo, -sp.oo, sp.zoo):
        assumptions.append("integral diverges")
    return format_result(result, assumptions=assumptions)
```

Key design points: **tool annotations** (`readOnlyHint`, `idempotentHint`) are
MCP protocol hints about behavior. **Annotated fields** provide the
descriptions the LLM sees in the tool schema. **Numerical fallback** means the
agent always gets a useful answer, even when no closed form exists. **`ctx=None`
default** lets the tool work both inside the MCP server and in unit tests.

## Add the differentiate tool

Create `src/tools/differentiate.py`. Same structure, different math. The key
difference is the `variables` parameter -- `["x", "x"]` for second derivative,
`["x", "y"]` for mixed partial. Optional `at_point` evaluates at specific
values (which are themselves SymPy expressions like `"pi/2"`).

```python
@tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def differentiate(
    expression: Annotated[str, Field(description="Function to differentiate.")],
    variables: Annotated[list[str], Field(description=(
        "Variables to differentiate with respect to, in order."))],
    at_point: Annotated[dict[str, str] | None, Field(description=(
        "Evaluate at this point. e.g. {'x': '0', 'y': 'pi/2'}."))] = None,
    ctx: Context = None,
) -> dict:
    """Compute ordinary, partial, or higher-order derivatives."""
    expr = parse_expression(expression, context="expression")
    symbols = [parse_symbol(v, context="variable") for v in variables]
    derivative = sp.diff(expr, *symbols)
    if at_point is not None:
        subs = parse_substitutions(at_point, context="at_point")
        derivative = derivative.subs(subs).doit()
    return format_result(derivative, assumptions=[])
```

See `calculus-helper/src/tools/differentiate.py` for the complete version with
full parameter descriptions and input validation.

## Test locally with pytest

```bash
make install
make test
```

Here is a representative test to verify the pattern:

```python
@pytest.mark.asyncio
async def test_indefinite_integral():
    result = await integrate(expression="x**2", variable="x", ctx=None)
    assert "x**3/3" in result["result"]
    assert any("constant" in n.lower() for n in result["assumptions"])

@pytest.mark.asyncio
async def test_caret_raises():
    with pytest.raises(ToolError, match=r"\*\*"):
        await integrate(expression="x^2", variable="x", ctx=None)
```

!!! note "Testing decorated functions"
    FastMCP 3.x `@tool` decorators return the original function with metadata
    attached. Call them directly in tests -- no server startup needed. Pass
    `ctx=None` to skip MCP context logging.

## Deploy to OpenShift

The project includes `openshift.yaml` (BuildConfig, Deployment, Service, Route)
and a `deploy.sh` script that applies them, uploads source, builds the
container, and waits for rollout:

```bash
./deploy.sh calculus-mcp
```

The Containerfile uses `registry.redhat.io/ubi9/python-311:latest` and sets the
HTTP transport environment for port 8080.

!!! warning "File permissions"
    The Containerfile includes `RUN find ./src -name "*.py" -exec chmod 644 {} \;`
    because OpenShift runs containers as an arbitrary non-root UID. Without
    world-readable permissions, the server starts with zero tools loaded.

## Test the MCP protocol with curl

Once deployed, test the server using streamable-http -- standard POSTs with
JSON-RPC payloads.

```bash
ROUTE=$(oc get route mcp-server -n calculus-mcp -o jsonpath='{.spec.host}')

# Initialize
curl -sk "https://$ROUTE/mcp/" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

# List tools
curl -sk "https://$ROUTE/mcp/" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call integrate
curl -sk "https://$ROUTE/mcp/" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"integrate","arguments":{"expression":"x**2","variable":"x"}}}'
```

The `tools/call` response returns the tool's output in the standard MCP
content format:

```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"result\": \"x**3/3\", \"latex\": \"\\\\frac{x^{3}}{3}\", \"is_exact\": true, \"assumptions\": [\"integration constant omitted\"]}"}]}}
```

## Reference

The finished product lives in `calculus-helper/` in this repository. Key files:

| File | What to check |
|------|--------------|
| `src/calc.py` | Full safe namespace, all parse/format functions |
| `src/tools/integrate.py` | Complete integrate tool with numerical fallback |
| `src/tools/differentiate.py` | Complete differentiate tool with point evaluation |
| `tests/tools/test_integrate.py` | Full test suite including edge cases |

## What's next

You have a working MCP server with calculus tools, deployed to OpenShift and
reachable over HTTPS. In [Module 4](04-wire-mcp-to-agent.md), you'll wire this
server into your agent so the LLM can call `integrate` and `differentiate` as
part of its reasoning loop.
