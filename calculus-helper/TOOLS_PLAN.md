# Tools Plan: Calculus Helper

## Overview

An MCP server that offloads calculus and symbolic-math computation from LLM agents. LLMs pattern-match math steps but don't reliably compute — a derivative's power rule looks right but the algebra after is often wrong, and definite integrals get fabricated. This server backs the agent with SymPy so answers are *computed*, not *guessed*.

**Who uses it**: Any agent that needs to answer calculus questions — tutoring agents, engineering assistants, physics homework helpers, technical-writing agents that need verified formulas.

**What it returns**: Exact symbolic results when possible, high-precision numerical results when not, plus LaTeX rendering for display. The agent chains tool outputs back in as inputs (the plain-text SymPy form is safe to re-parse).

## Design Principles Applied

From Anthropic's [Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents):

- **Fewer, more powerful tools.** Eight tools, each covering a full calculus operation with its natural sub-cases handled by parameters — not `partial_derivative`, `higher_order_derivative`, `directional_derivative` as separate tools.
- **Semantic returns, not cryptic identifiers.** Every result is a dict with named fields (`result`, `latex`, `is_exact`) rather than a bare string. `is_exact` tells the agent whether to trust the answer as symbolic truth or as a finite-precision approximation.
- **Coaching error messages.** Parse failures name the likely cause and give a concrete fix (`"Use ** not ^ for exponents"`), not a raw SymPy traceback.
- **Dual-format output.** Each result includes a plain-text SymPy string (for the agent to re-parse or chain) AND a LaTeX form (for the user to see). Agents don't have to choose.
- **Unambiguous parameter names.** `expression` not `expr`, `variable` not `v`, `lower_bound`/`upper_bound` not `a`/`b`.
- **Explicit assumptions.** When SymPy assumes a variable is real or positive to get a tractable answer, the response surfaces that assumption so the agent can flag it.

## Input Conventions (shared across all tools)

All expressions are passed as **strings in Python/SymPy syntax**:
- `x**2` not `x^2`
- `sin(x)`, `cos(x)`, `exp(x)`, `log(x)` (natural log), `sqrt(x)`
- Constants: `pi`, `E`, `oo` (infinity), `-oo`
- Multiple-variable expressions: `x**2 + y*sin(z)`

All parsing goes through a restricted `parse_expr` with a whitelisted symbol table — no arbitrary Python eval.

## Output Conventions (shared across all tools)

Unless otherwise noted, every tool returns a dict:

```python
{
  "result": str,           # SymPy string form, safe to re-parse
  "latex": str,            # LaTeX form for display
  "is_exact": bool,        # True = symbolic/exact, False = numerical approx
  "assumptions": list[str] # e.g. ["x is real"] — empty list if none
}
```

Tools with additional structure (e.g. `solve_equation` returning multiple roots) extend this with extra fields documented below.

## Tools

### differentiate

- **Purpose**: Compute derivatives — ordinary, partial, or higher-order. Handles single-variable and multivariable cases in one tool.
- **Parameters**:
  - `expression` (string, required): The function to differentiate, e.g. `"x**2 * sin(y)"`.
  - `variables` (list of strings, required): Variables to differentiate with respect to, in order. `["x"]` for `df/dx`. `["x", "x"]` for `d²f/dx²`. `["x", "y"]` for the mixed partial `∂²f/∂x∂y`.
  - `at_point` (dict of string→string, optional): If provided, evaluate the derivative at this point, e.g. `{"x": "0", "y": "pi"}`. Useful for getting a specific slope/value.
- **Returns**: Standard dict. If `at_point` given, `is_exact` reflects whether that evaluation stayed exact.
- **Error Cases**:
  - Parse failure → `ToolError` with guidance on syntax (e.g. "Use `**` not `^` for exponents").
  - Variable in `variables` or `at_point` not present in the expression → warning in `assumptions` but still computes (derivative w.r.t. an absent variable is 0, which is legitimate).
- **Example Usage**: Agent asked "What's the slope of f(x) = x³ - 2x at x = 1?" → calls `differentiate(expression="x**3 - 2*x", variables=["x"], at_point={"x": "1"})` → gets `{"result": "1", "latex": "1", "is_exact": true}`.

### integrate

- **Purpose**: Compute indefinite or definite integrals. Falls back to high-precision numerical integration when a closed form doesn't exist.
- **Parameters**:
  - `expression` (string, required): Integrand, e.g. `"exp(-x**2)"`.
  - `variable` (string, required): Variable of integration, e.g. `"x"`.
  - `lower_bound` (string, optional): Lower limit. Use `"-oo"` for −∞. If omitted → indefinite integral.
  - `upper_bound` (string, optional): Upper limit. Must be present iff `lower_bound` is.
  - `numerical` (boolean, optional, default `false`): If `true`, skip symbolic attempt and go straight to numerical quadrature (faster for hard integrals the agent knows won't close).
- **Returns**: Standard dict. For indefinite integrals, `result` includes `+ C` convention noted in `assumptions`. For definite integrals where symbolic fails, `is_exact` is `false` and `result` is a decimal to ~15 digits.
- **Error Cases**:
  - Only one of `lower_bound`/`upper_bound` given → `ToolError`: "Definite integral requires both bounds, or omit both for indefinite."
  - Divergent integral → `result` is `"oo"` or `"-oo"`, `assumptions` notes divergence.
  - Unparseable bound → `ToolError` pointing to which bound failed.
- **Example Usage**: "Integrate e^(-x²) from 0 to 1" → `integrate(expression="exp(-x**2)", variable="x", lower_bound="0", upper_bound="1")` → `{"result": "sqrt(pi)*erf(1)/2", "latex": "...", "is_exact": true}`.

### evaluate_limit

- **Purpose**: Compute limits at a finite point or at infinity, from either side or two-sided.
- **Parameters**:
  - `expression` (string, required): Expression whose limit to take, e.g. `"sin(x)/x"`.
  - `variable` (string, required): Variable approaching the limit point.
  - `point` (string, required): The limit point. Use `"oo"` for ∞, `"-oo"` for −∞, or any expression like `"0"`, `"pi/2"`.
  - `direction` (enum, optional, default `"both"`): `"left"` (x → point⁻), `"right"` (x → point⁺), or `"both"`. Ignored (with note) when `point` is ±∞.
- **Returns**: Standard dict. Result of `"oo"` / `"-oo"` means diverges to infinity. Two-sided limit that doesn't exist returns `result: "nan"` with `assumptions` explaining "left and right limits differ: L=…, R=…".
- **Error Cases**:
  - `direction="both"` where one-sided limits disagree → returned as `nan` with explanation, not an error. Agent should re-call with `"left"` and `"right"` to get both values.
- **Example Usage**: "What is lim x→0 of sin(x)/x?" → `evaluate_limit(expression="sin(x)/x", variable="x", point="0")` → `{"result": "1", "latex": "1", "is_exact": true}`.

### taylor_series

- **Purpose**: Compute Taylor/Maclaurin series expansion to a specified order.
- **Parameters**:
  - `expression` (string, required): Function to expand, e.g. `"exp(x)"`.
  - `variable` (string, required): Variable for expansion.
  - `around` (string, optional, default `"0"`): Point of expansion. `"0"` = Maclaurin series.
  - `order` (integer, required, min 1, max 20): Truncation order. Series is computed to `O(variable**order)`.
- **Returns**: Standard dict, plus:
  - `coefficients` (list of strings): The coefficient of each power `0..order-1`, for agents that want to reason termwise.
- **Error Cases**:
  - Order > 20 → `ToolError` with guidance: "Orders above 20 are rejected to prevent runaway computation. Request a lower order, or call `differentiate` repeatedly if you need specific higher-order coefficients."
  - Function not analytic at `around` → `ToolError` explaining which singularity was hit.
- **Example Usage**: "Taylor expand sin(x) around 0 to order 5" → returns `x - x**3/6 + x**5/120 + O(x**5)` plus per-term coefficients.

### solve_equation

- **Purpose**: Find symbolic (preferred) or numerical roots of an equation. Critical for agents finding critical points (solve f'(x) = 0), equilibria, or intersections.
- **Parameters**:
  - `equation` (string, required): Either an equation `"x**2 - 4 = 0"` or an expression to set equal to zero `"x**2 - 4"`.
  - `variable` (string, required): Variable to solve for.
  - `domain` (enum, optional, default `"complex"`): `"real"`, `"complex"`, or `"positive"`. Restricts the solution set.
  - `numerical_near` (string, optional): If provided (e.g. `"1.5"`), use numerical root-finding seeded at that value instead of symbolic solving. Use for transcendental equations where symbolic fails.
- **Returns**: Dict with:
  - `solutions` (list of strings): Each solution in SymPy form.
  - `solutions_latex` (list of strings): LaTeX form of each.
  - `is_exact` (bool): Whether the solutions are symbolic.
  - `count` (int): Number of solutions found (may be infinite → `count: -1` with a note).
  - `assumptions` (list of strings): e.g. `["solutions restricted to reals"]`.
- **Error Cases**:
  - No solution in domain → `solutions: []`, `count: 0`, not an error.
  - Symbolic solve fails and no `numerical_near` given → `ToolError`: "SymPy couldn't find a closed form. Re-call with `numerical_near` set to an approximate value near the root you want."
- **Example Usage**: Finding critical points of `x³ − 3x`: agent first calls `differentiate` to get `3*x**2 - 3`, then `solve_equation(equation="3*x**2 - 3", variable="x")` → `{"solutions": ["-1", "1"], ...}`.

### solve_ode

- **Purpose**: Solve ordinary differential equations (first-order, second-order, linear/nonlinear where SymPy can handle them).
- **Parameters**:
  - `equation` (string, required): ODE in SymPy syntax using `f(x)` and derivatives via `Derivative(f(x), x)` or the shorthand `f'(x)` — the tool accepts both and normalizes. Example: `"Derivative(f(x), x, x) + f(x) = 0"` or `"f''(x) + f(x) = 0"`.
  - `function` (string, required): The unknown function name, e.g. `"f"`.
  - `variable` (string, required): The independent variable, e.g. `"x"`.
  - `initial_conditions` (dict of string→string, optional): Map from condition to value, e.g. `{"f(0)": "1", "f'(0)": "0"}`. If provided, solves the IVP; otherwise returns the general solution with integration constants `C1`, `C2`, …
- **Returns**: Standard dict. `result` is the solved form, e.g. `"f(x) = cos(x)"`. `assumptions` notes the ODE classification SymPy used (e.g. "2nd order linear homogeneous with constant coefficients").
- **Error Cases**:
  - SymPy can't classify/solve → `ToolError`: "This ODE's form isn't in SymPy's solvable classes. Consider: (1) simplifying, (2) asking for a series solution via `taylor_series` on an assumed form, (3) numerical methods which this server doesn't currently provide."
  - IC doesn't match the expected function signature → `ToolError` with the expected shape.
- **Example Usage**: SHO equation: `solve_ode(equation="f''(x) + f(x) = 0", function="f", variable="x", initial_conditions={"f(0)": "1", "f'(0)": "0"})` → `{"result": "f(x) = cos(x)", ...}`.

### simplify_expression

- **Purpose**: Rewrite an expression in a canonical or requested form. Used by agents to check equivalence, clean up tool outputs before showing the user, or isolate a specific structural form.
- **Parameters**:
  - `expression` (string, required): Expression to transform.
  - `form` (enum, required): One of:
    - `"simplify"` — SymPy's general simplification (heuristic, best-effort canonical).
    - `"expand"` — distribute products, e.g. `(x+1)**3 → x**3 + 3*x**2 + 3*x + 1`.
    - `"factor"` — factor polynomials, e.g. `x**2 - 1 → (x-1)*(x+1)`.
    - `"collect"` — requires `variable`; group by powers of that variable.
    - `"trigsimp"` — simplify trigonometric expressions.
    - `"logcombine"` — combine/expand logarithms.
  - `variable` (string, optional): Required when `form="collect"`.
- **Returns**: Standard dict.
- **Error Cases**:
  - `form="collect"` without `variable` → `ToolError`: "`collect` requires a `variable` parameter — which variable to group by?"
- **Example Usage**: After integrating, agent gets back `sin(x)**2 + cos(x)**2 * tan(x) / tan(x)`; calls `simplify_expression(expression=..., form="simplify")` to get back `1` before showing the user.

### evaluate_numeric

- **Purpose**: Substitute concrete values for variables and compute a numerical result to specified precision. Replaces LLM hallucinated arithmetic.
- **Parameters**:
  - `expression` (string, required): Expression to evaluate.
  - `substitutions` (dict of string→string, optional): Map from variable name to value expression, e.g. `{"x": "2", "y": "pi/4"}`. Values are themselves SymPy expressions (so you can pass `"sqrt(2)"`, not just numbers).
  - `precision` (integer, optional, default `15`, max `50`): Significant decimal digits.
- **Returns**: Dict with:
  - `result` (string): Numerical value.
  - `exact_form` (string): If the expression simplifies to an exact form (like `sqrt(2)`), this is that form; otherwise same as `result`.
  - `latex` (string): LaTeX of the numerical result.
  - `is_exact` (bool): `true` if the result is a rational/exact form, `false` if a floating-point approximation.
  - `assumptions` (list): Notes like "Substituted before evaluation" or "Precision limited by …".
- **Error Cases**:
  - Expression has free variables after substitution → `ToolError` listing which variables still need values.
  - Precision > 50 → `ToolError`: "Max precision is 50 digits. For higher precision, call again with expression restructured to isolate the sensitive term."
- **Example Usage**: After derivatives/integrals give a symbolic answer like `sqrt(pi)*erf(1)/2`, agent calls `evaluate_numeric(expression="sqrt(pi)*erf(1)/2")` → `{"result": "0.746824132812427", "exact_form": "sqrt(pi)*erf(1)/2", "is_exact": false}`.

## Implementation Order

Implement in this order so each stage has something testable and later tools reuse earlier primitives:

1. **`simplify_expression`** — smallest surface area, exercises the shared parsing / output-formatting code that every other tool will use. Get the parse-error-message UX right here once.
2. **`evaluate_numeric`** — same parsing pipeline plus substitution. Low risk, high agent value on its own.
3. **`differentiate`** — first "real" calculus tool. Validates the `at_point` evaluation pattern that other tools will echo.
4. **`integrate`** — parallels `differentiate`. Exposes the symbolic-then-numeric fallback pattern that `solve_equation` also uses.
5. **`evaluate_limit`** — mostly thin wrapper over `sympy.limit`, but tests the direction enum and nan-handling conventions.
6. **`solve_equation`** — depends on patterns from `integrate` (numerical fallback) and `differentiate` (variable resolution). Unblocks "find critical points" workflows.
7. **`taylor_series`** — straightforward once `differentiate` works, but distinct enough to be last of the "standard" tools.
8. **`solve_ode`** — most complex. Different input grammar (derivatives, ICs). Implement last; failures here don't block the other seven.

Each tool should ship with:
- Unit tests covering: one happy path, one parse-error path, one "symbolic-fails-falls-back-to-numeric" path (where applicable), and one edge case specific to the tool (e.g. divergent integral, one-sided limit disagreement).
- A 2–3 line docstring summarizing what it does — this is what the agent sees.

## Dependencies

- **`sympy`** (>=1.12) — the engine. Provides symbolic calculus, numerical evaluation via `mpmath`, LaTeX printing, equation solving, ODE solving, series expansion.
- **`mpmath`** — transitively pulled in by SymPy; used for arbitrary-precision numerical evaluation in `evaluate_numeric` and numerical fallback in `integrate` / `solve_equation`.

No external APIs, no databases, no network. Pure-Python, stateless, deterministic. Runs happily in a container with no egress.

## Open Questions for Review

1. **`solve_ode` scope** — SymPy's ODE solver is powerful but has gaps (most nonlinear PDEs, some nonlinear ODEs). Ship with a clear error message when it can't solve, or drop `solve_ode` from v1 and add later? Current plan: ship it, with the coaching error message.
2. **Input syntax strictness** — do we want to accept `^` for exponents and auto-translate to `**`? It's friendlier but hides a real confusion (in SymPy `^` is XOR, which can silently produce wrong answers on integer inputs like `2^3 = 1`). Current plan: reject `^`, coach the agent to use `**`.
3. **LaTeX in every response** — adds ~20% to response size. Worth it for the display use case, or make it an opt-in `include_latex` param? Current plan: always include; it's small and the alternative is the agent having to make a second call.
4. **Step-by-step output** — SymPy doesn't natively produce human-readable solution steps (that requires a library like `sympy-gamma`). Out of scope for v1; agents that want pedagogical step-by-step can narrate around the computed result. Agree?
