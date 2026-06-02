# 3. Build an MCP Server

Your agent is running in OpenShift, but it has no real tools. In this module
you'll build an MCP server that exposes calculus operations -- integration and
differentiation -- as tools any MCP client can call. By the end, the server
will be deployed and testable via the streamable-http protocol.

## Scaffold the MCP server

Make sure you're in the parent directory (not inside `calculus-agent/`)
before scaffolding. The MCP server is a separate project that lives
alongside the agent:

```bash
cd ..
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

## Prepare the project

### Remove scaffold examples

The scaffold includes example tools and tests to show the expected structure.
Remove them to start fresh:

```bash
./remove_examples.sh
```

### Add the sympy dependency

The calculus tools use SymPy for symbolic math. Add it to the project's
dependencies:

```bash
echo "sympy>=1.13" >> requirements.txt
make install
```

## Build the shared parsing layer

Before writing tools, create `src/calc.py` -- a shared module for expression
parsing and result formatting. It lives outside `src/tools/` so the
auto-discovery scanner doesn't try to find tool decorators in it.

Create the file:

```bash
touch src/calc.py
```

The sections below walk through the key pieces of `calc.py`. If you prefer
to skip the incremental build, copy the complete file from the finished
example in the repo:

```bash
cp ../../examples/calculus-helper/src/calc.py src/calc.py
```

If you cloned the repo to a different location, the file is at
[`calculus-helper/src/calc.py`](https://github.com/fips-agents/examples/blob/main/calculus-helper/src/calc.py).

??? note "Complete `src/calc.py` (click to expand)"

    ```python
    """Shared parsing and formatting helpers for the calculus tools.

    All calculus tools use SymPy for symbolic math. This module centralises the
    cross-cutting concerns so every tool behaves consistently:

    - ``parse_expression`` -- parse a user string into a SymPy expression using a
      restricted allowlist namespace (no arbitrary Python ``eval``), with
      coaching-style error messages for the most common syntax mistakes.
    - ``parse_symbol`` -- parse a bare identifier into a ``sympy.Symbol``.
    - ``parse_substitutions`` -- parse a ``{var_name: value_expr}`` dict.
    - ``format_result`` -- build the standard output dict
      (``result`` / ``latex`` / ``is_exact`` / ``assumptions``) used by every tool.

    Imported by each tool under ``src/tools/``.  This file deliberately lives
    outside ``src/tools/`` so FastMCP's ``FileSystemProvider`` never scans it for
    tool decorators.
    """

    from __future__ import annotations

    from tokenize import TokenError
    from typing import Any

    import sympy as sp
    from fastmcp.exceptions import ToolError
    from sympy.parsing.sympy_parser import (
        implicit_application,
        implicit_multiplication,
        parse_expr,
        standard_transformations,
    )

    # ---------------------------------------------------------------------------
    # Parsing
    # ---------------------------------------------------------------------------

    # Security: only these names are available inside parsed expressions.
    # Anything not listed here (eval, __import__, open, os, etc.) is
    # inaccessible.  Unknown identifiers become fresh SymPy Symbols rather
    # than raising -- so "theta" works without being allowlisted, but
    # "os.system" becomes Symbol("os") * Symbol("system"), which is harmless.
    _SAFE_NAMESPACE: dict[str, Any] = {
        # Constants
        "pi": sp.pi,
        "E": sp.E,
        "I": sp.I,
        "oo": sp.oo,
        "inf": sp.oo,
        "infinity": sp.oo,
        "nan": sp.nan,
        "NaN": sp.nan,
        # Trig
        "sin": sp.sin,
        "cos": sp.cos,
        "tan": sp.tan,
        "sec": sp.sec,
        "csc": sp.csc,
        "cot": sp.cot,
        "asin": sp.asin,
        "acos": sp.acos,
        "atan": sp.atan,
        "atan2": sp.atan2,
        # Hyperbolic
        "sinh": sp.sinh,
        "cosh": sp.cosh,
        "tanh": sp.tanh,
        "asinh": sp.asinh,
        "acosh": sp.acosh,
        "atanh": sp.atanh,
        # Exp / log / roots
        "exp": sp.exp,
        "log": sp.log,
        "ln": sp.log,          # ln is an alias for the natural log
        "log10": lambda x: sp.log(x, 10),
        "log2": lambda x: sp.log(x, 2),
        "sqrt": sp.sqrt,
        "cbrt": sp.cbrt,
        # Inverse trig -- accept both "asin" and "arcsin" spellings so the
        # LLM does not need to guess which convention the server expects.
        "arcsin": sp.asin,
        "arccos": sp.acos,
        "arctan": sp.atan,
        "arctan2": sp.atan2,
        "arcsinh": sp.asinh,
        "arccosh": sp.acosh,
        "arctanh": sp.atanh,
        # Misc
        "Abs": sp.Abs,
        "abs": sp.Abs,
        "erf": sp.erf,
        "erfc": sp.erfc,
        "gamma": sp.gamma,
        "factorial": sp.factorial,
        "floor": sp.floor,
        "ceiling": sp.ceiling,
        "ceil": sp.ceiling,
        "Min": sp.Min,
        "Max": sp.Max,
        # ODE / equation helpers
        "Derivative": sp.Derivative,
        "Function": sp.Function,
        "Eq": sp.Eq,
    }

    # Why no split_symbols?  It would rewrite "log10(x)" as
    # "l*o*g*10*x", silently producing wrong answers.  We use
    # implicit_multiplication (so "2x" means "2*x") and
    # implicit_application without the letter-level split.
    _TRANSFORMATIONS = standard_transformations + (
        implicit_multiplication,
        implicit_application,
    )


    def parse_expression(expr_str: str, *, context: str = "expression") -> sp.Expr:
        """Parse a user-supplied expression string into a SymPy expression.

        Uses the restricted _SAFE_NAMESPACE so arbitrary Python code cannot
        be evaluated.  The context parameter labels which input field failed
        (e.g. "integrand", "lower bound") so the calling agent knows exactly
        which argument to fix.
        """
        if not isinstance(expr_str, str):
            raise ToolError(
                f"Expected a string for {context}, got {type(expr_str).__name__}."
            )
        stripped = expr_str.strip()
        if not stripped:
            raise ToolError(f"{context} cannot be empty.")

        # Catch the most common mistake BEFORE the parser silently mis-reads
        # it: ^ is bitwise XOR in Python, not exponentiation.
        if "^" in stripped:
            raise ToolError(
                f"Invalid {context}: '{stripped}'. Use '**' for exponents, not '^'. "
                "In Python/SymPy '^' is bitwise XOR and silently produces wrong "
                "answers on integer inputs (e.g. 2^3 = 1, not 8). "
                "Rewrite the expression with '**' and try again."
            )

        try:
            return parse_expr(
                stripped,
                local_dict=dict(_SAFE_NAMESPACE),
                transformations=_TRANSFORMATIONS,
            )
        except (SyntaxError, TokenError, ValueError, TypeError, NameError) as e:
            raise ToolError(
                f"Could not parse {context}: '{stripped}'. "
                f"Parser said: {type(e).__name__}: {e}. "
                "Check for balanced parentheses. Use '**' for exponents, '*' for "
                "multiplication, and Python-style function names "
                "(sin, cos, exp, log, sqrt). "
                "Use 'pi' for pi, 'E' for Euler's constant, 'oo' for infinity."
            )


    def parse_symbol(var_str: str, *, context: str = "variable") -> sp.Symbol:
        """Parse a variable name into a SymPy Symbol.

        Accepts a bare identifier ("x", "theta", "t_1").  Anything else --
        expressions, numbers, operators -- is rejected so the agent knows
        the slot expects a name, not an expression.
        """
        if not isinstance(var_str, str):
            raise ToolError(
                f"Expected a string for {context}, got {type(var_str).__name__}."
            )
        stripped = var_str.strip()
        if not stripped:
            raise ToolError(f"{context} cannot be empty.")
        if not stripped.isidentifier():
            raise ToolError(
                f"{context} '{stripped}' is not a valid identifier. "
                "Use a simple name like 'x', 'theta', or 't_1' -- "
                "no spaces, operators, or leading digits."
            )
        return sp.Symbol(stripped)


    def parse_substitutions(
        subs: dict[str, str] | None,
        *,
        context: str = "substitutions",
    ) -> dict[sp.Symbol, sp.Expr]:
        """Parse {var_name: value_expression} strings into SymPy form.

        Values are themselves expressions, so callers can pass "sqrt(2)" or
        "pi/4" as substitution targets -- not just bare numbers.
        """
        if not subs:
            return {}
        result: dict[sp.Symbol, sp.Expr] = {}
        for name, value in subs.items():
            sym = parse_symbol(name, context=f"{context} key '{name}'")
            expr = parse_expression(value, context=f"{context} value for '{name}'")
            result[sym] = expr
        return result


    # ---------------------------------------------------------------------------
    # Formatting
    # ---------------------------------------------------------------------------


    def is_exact(expr: Any) -> bool:
        """Return True when expr is a symbolic / exact SymPy object.

        Heuristic: "contains no sympy.Float".  Rational numbers, radicals,
        trig at exact angles, oo, and nan are all considered exact.
        Anything produced by evalf / sp.N generally contains Float.
        """
        try:
            basic = expr if isinstance(expr, sp.Basic) else sp.sympify(expr)
        except (sp.SympifyError, TypeError):
            return True
        try:
            return not basic.has(sp.Float)
        except AttributeError:
            return True


    def format_result(
        expr: Any,
        *,
        assumptions: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the standard output dict every calculus tool returns.

        Returns a dict with result (str), latex (str), is_exact (bool),
        assumptions (list[str]), plus any keys from extra.  Returning the
        same shape from every tool means the consuming agent can use a
        single parsing strategy for all calculus results.
        """
        if assumptions is None:
            assumptions = []

        if isinstance(expr, sp.Basic):
            sympy_expr: sp.Basic = expr
        else:
            try:
                sympy_expr = sp.sympify(expr)
            except (sp.SympifyError, TypeError):
                out: dict[str, Any] = {
                    "result": str(expr),
                    "latex": str(expr),
                    "is_exact": True,
                    "assumptions": list(assumptions),
                }
                if extra:
                    out.update(extra)
                return out

        out = {
            "result": str(sympy_expr),
            "latex": sp.latex(sympy_expr),
            "is_exact": is_exact(sympy_expr),
            "assumptions": list(assumptions),
        }
        if extra:
            out.update(extra)
        return out
    ```

### The safe namespace

The core idea is an **allowlist** of names available inside parsed expressions.
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
    execution. The allowlist namespace restricts parsing to mathematical
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

### parse_symbol

Validates that a string is a bare identifier and returns a SymPy `Symbol`.
Tools use this for variable names (`"x"`, `"theta"`) rather than
`parse_expression`, which would accept operators and numbers:

```python
def parse_symbol(var_str: str, *, context: str = "variable") -> sp.Symbol:
    stripped = var_str.strip()
    if not stripped:
        raise ToolError(f"{context} cannot be empty.")
    if not stripped.isidentifier():
        raise ToolError(
            f"{context} '{stripped}' is not a valid identifier. "
            "Use a simple name like 'x', 'theta', or 't_1' -- "
            "no spaces, operators, or leading digits."
        )
    return sp.Symbol(stripped)
```

### parse_substitutions

Parses a `{var_name: value_expression}` dict into SymPy form. Values are
themselves expressions, so callers can pass `"sqrt(2)"` or `"pi/4"` as
substitution targets -- not just bare numbers. The `differentiate` tool's
`at_point` parameter uses this:

```python
def parse_substitutions(
    subs: dict[str, str] | None, *, context: str = "substitutions",
) -> dict[sp.Symbol, sp.Expr]:
    if not subs:
        return {}
    result: dict[sp.Symbol, sp.Expr] = {}
    for name, value in subs.items():
        sym = parse_symbol(name, context=f"{context} key '{name}'")
        expr = parse_expression(value, context=f"{context} value for '{name}'")
        result[sym] = expr
    return result
```

## Add the integrate tool

Create `src/tools/integrate.py`. This is the primary walkthrough --
`differentiate.py` follows the same pattern.

```bash
touch src/tools/integrate.py
```

Or copy the complete file from the reference project:

```bash
cp ../../examples/calculus-helper/src/tools/integrate.py src/tools/integrate.py
```

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

Here is the complete file. You can also copy it from the reference project.

??? note "Complete `src/tools/integrate.py` (click to expand)"

    ```python
    """Compute indefinite or definite integrals of a symbolic expression with numerical fallback."""

    from typing import Annotated

    import sympy as sp
    from fastmcp import Context
    from fastmcp.exceptions import ToolError
    from fastmcp.tools import tool
    from pydantic import Field

    from src.calc import format_result, parse_expression, parse_symbol


    @tool(
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def integrate(
        expression: Annotated[
            str,
            Field(
                description=(
                    "The integrand in Python/SymPy syntax, e.g. 'exp(-x**2)', 'sin(x)*cos(x)'. "
                    "Use '**' not '^' for exponents."
                )
            ),
        ],
        variable: Annotated[
            str,
            Field(description="Variable of integration, e.g. 'x'."),
        ],
        lower_bound: Annotated[
            str | None,
            Field(
                description=(
                    "Lower limit for a definite integral. "
                    "Use '-oo' for minus-infinity, or any SymPy expression like '0', 'pi', 'exp(1)'. "
                    "Must be provided together with upper_bound, or omitted for indefinite."
                )
            ),
        ] = None,
        upper_bound: Annotated[
            str | None,
            Field(
                description=(
                    "Upper limit for a definite integral. "
                    "Use 'oo' for plus-infinity, or any SymPy expression like '1', 'pi', 'sqrt(2)'. "
                    "Must be provided together with lower_bound, or omitted for indefinite."
                )
            ),
        ] = None,
        numerical: Annotated[
            bool,
            Field(
                description=(
                    "If true, skip symbolic attempt and compute numerically. "
                    "Useful for integrands known to have no closed form. "
                    "Requires lower_bound and upper_bound. Default false."
                )
            ),
        ] = False,
        ctx: Context = None,
    ) -> dict:
        """Compute indefinite or definite integrals, falling back to numerical when closed form unavailable.

        For indefinite integrals the integration constant is omitted and noted in assumptions.
        For definite integrals where SymPy cannot find a closed form, falls back to high-precision
        numerical evaluation (~15 significant digits) and sets is_exact=False in the result.

        Bound ordering: if `lower_bound` > `upper_bound` the returned value is the *negative*
        of the swapped integral, following the standard convention.
        """
        if ctx is not None:
            await ctx.info(
                f"integrate: expression={expression!r} variable={variable!r} "
                f"lower={lower_bound!r} upper={upper_bound!r} numerical={numerical}"
            )

        # Validate that bounds are either both given or both absent.
        has_lower = lower_bound is not None
        has_upper = upper_bound is not None
        if has_lower != has_upper:
            raise ToolError(
                "Definite integral requires both bounds, or omit both for indefinite. "
                f"Got lower_bound={lower_bound!r}, upper_bound={upper_bound!r}."
            )

        definite = has_lower and has_upper

        if numerical and not definite:
            raise ToolError(
                "Numerical integration requires both lower_bound and upper_bound."
            )

        expr = parse_expression(expression, context="expression")
        sym = parse_symbol(variable, context="variable")
        assumptions: list[str] = []

        # --- Indefinite integral ---
        if not definite:
            result = sp.integrate(expr, sym)
            assumptions.append("integration constant omitted")
            return format_result(result, assumptions=assumptions)

        # --- Definite integral ---
        low = parse_expression(lower_bound, context="lower bound")
        high = parse_expression(upper_bound, context="upper bound")

        if numerical:
            # Caller explicitly asked for numerical -- skip symbolic entirely.
            num_result = sp.Integral(expr, (sym, low, high)).evalf()
            return format_result(num_result, assumptions=assumptions)

        # Symbolic attempt first.
        result = sp.integrate(expr, (sym, low, high))

        # If SymPy returned an unevaluated Integral, fall back to numerical.
        if isinstance(result, sp.Integral):
            num_result = result.evalf()
            return format_result(num_result, assumptions=assumptions)

        # Divergent result -- valid symbolic answer, just note it.
        if result in (sp.oo, -sp.oo, sp.zoo):
            assumptions.append("integral diverges")

        return format_result(result, assumptions=assumptions)
    ```

## Add the differentiate tool

Create `src/tools/differentiate.py`. Same structure, different math. The key
difference is the `variables` parameter -- `["x", "x"]` for second derivative,
`["x", "y"]` for mixed partial. Optional `at_point` evaluates at specific
values (which are themselves SymPy expressions like `"pi/2"`).

```bash
touch src/tools/differentiate.py
```

Or copy the complete file from the reference project:

```bash
cp ../../examples/calculus-helper/src/tools/differentiate.py src/tools/differentiate.py
```

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

??? note "Complete `src/tools/differentiate.py` (click to expand)"

    ```python
    """Compute ordinary, partial, or higher-order derivatives of a symbolic expression."""

    from typing import Annotated

    import sympy as sp
    from fastmcp import Context
    from fastmcp.exceptions import ToolError
    from fastmcp.tools import tool
    from pydantic import Field

    from src.calc import format_result, parse_expression, parse_substitutions, parse_symbol


    @tool(
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def differentiate(
        expression: Annotated[
            str,
            Field(
                description=(
                    "The function to differentiate, in Python/SymPy syntax. "
                    "e.g. 'x**2 * sin(y)', 'exp(-x**2)'. Use '**' not '^' for exponents."
                )
            ),
        ],
        variables: Annotated[
            list[str],
            Field(
                description=(
                    "Variables to differentiate with respect to, in order. "
                    "['x'] -> df/dx.  ['x', 'x'] -> d^2f/dx^2 (repeat for higher order). "
                    "['x', 'y'] -> mixed partial d^2f/dxdy."
                )
            ),
        ],
        at_point: Annotated[
            dict[str, str] | None,
            Field(
                description=(
                    "Optional: evaluate the derivative at this point. "
                    "Map from variable name to value expression, "
                    "e.g. {'x': '0', 'y': 'pi/2'}. Values are SymPy expressions."
                )
            ),
        ] = None,
        ctx: Context = None,
    ) -> dict:
        """Compute ordinary, partial, or higher-order derivatives of a symbolic expression.

        Supports single-variable derivatives, higher-order derivatives (repeat the variable),
        and mixed partial derivatives. Optionally evaluates the result at a specific point.
        Returns the derivative in both plain-text SymPy form and LaTeX, plus an is_exact flag.
        """
        if ctx is not None:
            await ctx.info(
                f"differentiate: expression={expression!r} variables={variables!r} "
                f"at_point={at_point!r}"
            )

        if not variables:
            raise ToolError(
                "`variables` must contain at least one variable to differentiate with respect to."
            )

        expr = parse_expression(expression, context="expression")

        # Parse each differentiation variable; check for free symbols to warn
        # when the derivative is trivially zero.
        expr_free_syms = {str(s) for s in expr.free_symbols}
        symbols: list[sp.Symbol] = []
        assumptions: list[str] = []

        for var_name in variables:
            sym = parse_symbol(var_name, context="variable")
            symbols.append(sym)
            if var_name not in expr_free_syms:
                assumptions.append(
                    f"'{var_name}' not present in expression; derivative w.r.t. '{var_name}' is 0"
                )

        # Compute the derivative.  sp.diff(expr, x, y) gives d^2/dxdy.
        derivative = sp.diff(expr, *symbols)

        # Evaluate at a point if requested.
        if at_point is not None:
            subs = parse_substitutions(at_point, context="at_point")
            for sym in subs:
                if str(sym) not in expr_free_syms:
                    assumptions.append(
                        f"'{sym}' not present in expression; substitution has no effect"
                    )
            derivative = derivative.subs(subs)
            derivative = derivative.doit()

        return format_result(derivative, assumptions=assumptions)
    ```

## Test locally with pytest

Install dependencies, then create the test directory and test file:

```bash
make install
mkdir -p tests/tools
touch tests/tools/__init__.py
touch tests/tools/test_calculus.py
```

The tests call the `@tool`-decorated functions directly -- no server startup
needed. FastMCP 3.x decorators return the original function with metadata
attached, so you can import and call them like any async function. Pass
`ctx=None` to skip MCP context logging.

Here are the key tests inline. The collapsible block below contains the
complete file.

**Integration tests** -- verify indefinite, definite, numerical, and error paths:

```python
@pytest.mark.asyncio
async def test_indefinite_integral():
    """Indefinite integral of x^2 should be x^3/3."""
    result = await integrate(expression="x**2", variable="x", ctx=None)
    assert "x**3/3" in result["result"]
    assert result["is_exact"] is True
    assert any("constant" in a.lower() for a in result["assumptions"])


@pytest.mark.asyncio
async def test_definite_integral():
    """Definite integral of x from 0 to 1 should be 1/2."""
    result = await integrate(
        expression="x", variable="x",
        lower_bound="0", upper_bound="1", ctx=None,
    )
    assert result["result"] == "1/2"
    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_caret_raises_tool_error():
    """Using ^ instead of ** should raise a helpful error."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await integrate(expression="x^2", variable="x", ctx=None)
```

**Differentiation tests** -- verify first, second, and point-evaluated derivatives:

```python
@pytest.mark.asyncio
async def test_first_derivative():
    """First derivative of x^3 should be 3*x^2."""
    result = await differentiate(
        expression="x**3", variables=["x"], ctx=None,
    )
    assert result["result"] == "3*x**2"


@pytest.mark.asyncio
async def test_derivative_at_point():
    """Derivative of x^2 evaluated at x=3 should be 6."""
    result = await differentiate(
        expression="x**2", variables=["x"],
        at_point={"x": "3"}, ctx=None,
    )
    assert result["result"] == "6"
```

??? note "Complete `tests/tools/test_calculus.py` (click to expand)"

    ```python
    """Tests for the calculus MCP tools.

    These tests call the @tool-decorated functions directly -- no server
    startup needed. FastMCP 3.x decorators return the original function
    with metadata attached, so you can import and call them like any
    async function. Pass ctx=None to skip MCP context logging.
    """

    import pytest
    from fastmcp.exceptions import ToolError

    from src.tools.integrate import integrate
    from src.tools.differentiate import differentiate


    # ---------------------------------------------------------------------------
    # Integration tests
    # ---------------------------------------------------------------------------


    @pytest.mark.asyncio
    async def test_indefinite_integral():
        """Indefinite integral of x^2 should be x^3/3."""
        result = await integrate(expression="x**2", variable="x", ctx=None)
        assert "x**3/3" in result["result"]
        assert result["is_exact"] is True
        # Indefinite integrals should note the omitted constant.
        assert any("constant" in a.lower() for a in result["assumptions"])


    @pytest.mark.asyncio
    async def test_definite_integral():
        """Definite integral of x from 0 to 1 should be 1/2."""
        result = await integrate(
            expression="x", variable="x",
            lower_bound="0", upper_bound="1", ctx=None,
        )
        assert result["result"] == "1/2"
        assert result["is_exact"] is True


    @pytest.mark.asyncio
    async def test_numerical_integration():
        """Numerical integration of exp(-x^2) from 0 to 1 (no closed form)."""
        result = await integrate(
            expression="exp(-x**2)", variable="x",
            lower_bound="0", upper_bound="1",
            numerical=True, ctx=None,
        )
        # The Gauss error function integral is approximately 0.7468
        assert float(result["result"]) == pytest.approx(0.7468, abs=0.001)
        assert result["is_exact"] is False


    @pytest.mark.asyncio
    async def test_caret_raises_tool_error():
        """Using ^ instead of ** should raise a helpful error."""
        with pytest.raises(ToolError, match=r"\*\*"):
            await integrate(expression="x^2", variable="x", ctx=None)


    @pytest.mark.asyncio
    async def test_missing_bound_raises():
        """Providing only one bound should raise an error."""
        with pytest.raises(ToolError, match="both bounds"):
            await integrate(
                expression="x", variable="x",
                lower_bound="0", ctx=None,
            )


    # ---------------------------------------------------------------------------
    # Differentiation tests
    # ---------------------------------------------------------------------------


    @pytest.mark.asyncio
    async def test_first_derivative():
        """First derivative of x^3 should be 3*x^2."""
        result = await differentiate(
            expression="x**3", variables=["x"], ctx=None,
        )
        assert result["result"] == "3*x**2"


    @pytest.mark.asyncio
    async def test_second_derivative():
        """Second derivative of x^3 (repeat variable) should be 6*x."""
        result = await differentiate(
            expression="x**3", variables=["x", "x"], ctx=None,
        )
        assert result["result"] == "6*x"


    @pytest.mark.asyncio
    async def test_derivative_at_point():
        """Derivative of x^2 evaluated at x=3 should be 6."""
        result = await differentiate(
            expression="x**2", variables=["x"],
            at_point={"x": "3"}, ctx=None,
        )
        assert result["result"] == "6"


    @pytest.mark.asyncio
    async def test_empty_expression_raises():
        """Empty expression should raise a clear error."""
        with pytest.raises(ToolError, match="cannot be empty"):
            await differentiate(expression="", variables=["x"], ctx=None)
    ```

Run the tests:

```bash
make test
```

!!! note "Testing decorated functions"
    FastMCP 3.x `@tool` decorators return the original function with metadata
    attached. Call them directly in tests -- no server startup needed. Pass
    `ctx=None` to skip MCP context logging.

## Deploy to OpenShift

The project includes `openshift.yaml` (BuildConfig, Deployment, Service,
Route). Deploy with a single command:

```bash
fips-agents deploy --context="$CTX" -n calculus-mcp
```

This applies `openshift.yaml`, uploads your source, builds the container in
the cluster, and waits for the rollout to complete.

Alternatively, use the bundled shell script:

```bash
./deploy.sh calculus-mcp
```

Both commands do the same thing. The Containerfile uses
`registry.redhat.io/ubi9/python-311:latest` and sets the HTTP transport
environment for port 8080.

!!! warning "File permissions"
    The Containerfile includes `RUN find ./src -name "*.py" -exec chmod 644 {} \;`
    because OpenShift runs containers as an arbitrary non-root UID. Without
    world-readable permissions, the server starts with zero tools loaded.

## Test the MCP protocol with curl

Once deployed, test the server using streamable-http -- standard POSTs with
JSON-RPC payloads. The streamable-http transport requires two headers on every
request: `Content-Type: application/json` and `Accept: application/json,
text/event-stream`. After `initialize`, subsequent requests must also include
the `Mcp-Session-Id` returned in the response headers.

```bash
ROUTE=$(oc get route mcp-server -n calculus-mcp --context="$CTX" -o jsonpath='{.spec.host}')

# Initialize -- dump response headers so we can extract the session ID
curl -sk "https://$ROUTE/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -D /tmp/mcp-headers.txt \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

The response headers include an `Mcp-Session-Id` that you'll need for
subsequent requests. Capture it:

```bash
SESSION=$(grep -i mcp-session-id /tmp/mcp-headers.txt | tr -d '\r' | awk '{print $2}')
echo "SESSION=$SESSION"
```

The `echo` should print a non-empty UUID-like string. If `SESSION` is empty,
the `initialize` call did not return a session header -- inspect
`/tmp/mcp-headers.txt` directly to see the raw response (most often the route
returned an HTML error page, or the server rejected the request before
assigning a session). Don't continue until `SESSION` is populated; every
subsequent request will fail with a 4xx otherwise.

Responses arrive as SSE events, prefixed with `event: message\ndata: ...`.
Most terminals display the JSON payload inline.

```bash
# List tools
curl -sk "https://$ROUTE/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call integrate
curl -sk "https://$ROUTE/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
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
