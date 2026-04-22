# Calculus Helper MCP Server

An MCP server that offloads symbolic calculus to [SymPy](https://www.sympy.org) so LLM agents get *computed* answers — derivatives, integrals, limits, series, ODEs — instead of pattern-matched hallucinations. Every result comes back in both machine-readable SymPy form (safe to re-parse and chain) and LaTeX (for display).

Built on [FastMCP 3.x](https://gofastmcp.com) with filesystem-based tool discovery, streamable-HTTP transport for OpenShift, and STDIO for local development.

## Tools

| Tool | Purpose |
|---|---|
| [`differentiate`](#differentiate) | Ordinary, partial, or higher-order derivatives, optionally evaluated at a point |
| [`integrate`](#integrate) | Indefinite or definite integrals, with numerical fallback |
| [`evaluate_limit`](#evaluate_limit) | Limits at a point or at infinity, from either side or two-sided |
| [`taylor_series`](#taylor_series) | Taylor/Maclaurin expansion with per-term coefficients |
| [`solve_equation`](#solve_equation) | Symbolic or numerical roots, optionally restricted by domain |
| [`solve_ode`](#solve_ode) | Ordinary differential equations with optional initial conditions |
| [`simplify_expression`](#simplify_expression) | Simplify / expand / factor / collect / trigsimp / logcombine |
| [`evaluate_numeric`](#evaluate_numeric) | Substitute concrete values and compute to arbitrary precision |

### Shared contract

Every tool returns a dict with these keys:

| Key | Type | Meaning |
|---|---|---|
| `result` | `str` | The answer in SymPy string form. Safe to pass back into another tool as input. |
| `latex` | `str` | LaTeX rendering of `result`, for display. |
| `is_exact` | `bool` | `true` for symbolic/exact answers (rationals, radicals, `oo`); `false` for `Float` approximations. |
| `assumptions` | `list[str]` | Notes the tool made while computing — singularities hit, constants omitted, directions disregarded, etc. Surface these to the user. |

Tools that return a set of answers (`solve_equation`) or structured auxiliary data (`taylor_series`) extend the dict with extra keys documented per-tool.

### Input conventions

All math is passed as **Python/SymPy syntax strings**:

- `x**2` not `x^2` (the server rejects `^` with a coaching message — in SymPy `^` is bitwise XOR and `2^3 = 1`).
- `sin(x)`, `cos(x)`, `exp(x)`, `log(x)` (natural log), `sqrt(x)`, `log10(x)`, `log2(x)`, `arcsin(x)`, `arctan(x)`.
- Constants: `pi`, `E`, `oo` (or `inf` / `infinity`), `-oo`.
- Parsing uses a restricted whitelist — no arbitrary Python `eval`.

---

### `differentiate`

Compute an ordinary, partial, or higher-order derivative. Supports evaluation at a point.

**Parameters:**
- `expression` (string, required) — the function to differentiate, e.g. `"x**2 * sin(y)"`.
- `variables` (list[string], required) — differentiation variables, in order. `["x"]` → `df/dx`. `["x","x"]` → `d²f/dx²`. `["x","y"]` → mixed partial `∂²f/∂x∂y`.
- `at_point` (dict[string,string], optional) — evaluate the derivative at this point, e.g. `{"x": "0", "y": "pi/2"}`.

**Example:** slope of `x³ − 2x` at `x = 1`:
```json
{"expression": "x**3 - 2*x", "variables": ["x"], "at_point": {"x": "1"}}
→ {"result": "1", "latex": "1", "is_exact": true, "assumptions": []}
```

---

### `integrate`

Compute indefinite or definite integrals. If SymPy cannot close a definite integral symbolically, the tool falls back to high-precision numerical quadrature automatically.

**Parameters:**
- `expression` (string, required) — integrand.
- `variable` (string, required) — variable of integration.
- `lower_bound` (string, optional) — lower limit. Use `"-oo"` for −∞.
- `upper_bound` (string, optional) — upper limit. Must be present iff `lower_bound` is.
- `numerical` (bool, optional, default `false`) — skip symbolic and go straight to numerical.

**Bound ordering**: if `lower_bound > upper_bound`, the result is the *negative* of the swapped integral, per the standard convention `∫[a,b] = −∫[b,a]`. This is mathematically correct, not a bug.

**Example:** `∫₀¹ e^(−x²) dx`:
```json
{"expression": "exp(-x**2)", "variable": "x", "lower_bound": "0", "upper_bound": "1"}
→ {"result": "sqrt(pi)*erf(1)/2", "is_exact": true, ...}
```

---

### `evaluate_limit`

Compute a limit at a finite point or at ±∞, from either side or two-sided.

**Parameters:**
- `expression` (string, required).
- `variable` (string, required).
- `point` (string, required) — the limit point. `"oo"` / `"-oo"` for infinity.
- `direction` (`"left"` | `"right"` | `"both"`, default `"both"`).

**Behaviour:** for `direction="both"` at a finite point, the tool computes left and right limits separately and compares them. If they disagree, `result` is `"nan"` with the two one-sided values listed in `assumptions`. At infinity, `direction` is ignored and a note is added.

**Example:** `lim_{x→0} sin(x)/x`:
```json
{"expression": "sin(x)/x", "variable": "x", "point": "0"}
→ {"result": "1", "is_exact": true, ...}
```

---

### `taylor_series`

Compute the Taylor/Maclaurin expansion to a specified order. Returns both the truncated polynomial *and* a coefficient list for term-wise reasoning.

**Parameters:**
- `expression` (string, required).
- `variable` (string, required).
- `around` (string, optional, default `"0"`) — expansion point.
- `order` (int, optional, default `6`, 1–20) — truncation order.

**Extra return keys:** `coefficients` (list[string]) — coefficients of powers `0` through `order-1`.

**Errors:** raises `ToolError` if the function is not analytic at `around` (pole, branch point).

**Example:** `sin(x)` at 0 to order 6:
```json
{"expression": "sin(x)", "variable": "x", "order": 6}
→ {"result": "x**5/120 - x**3/6 + x",
   "coefficients": ["0", "1", "0", "-1/6", "0", "1/120"], ...}
```

---

### `solve_equation`

Find roots symbolically (preferred) or numerically (via `numerical_near`).

**Parameters:**
- `equation` (string, required) — either `"lhs = rhs"` or just `"expr"` (taken as `expr = 0`).
- `variable` (string, required).
- `domain` (`"real"` | `"complex"` | `"positive"`, default `"complex"`).
- `numerical_near` (string, optional) — seed value for `nsolve` when symbolic solving fails (e.g. transcendental equations).

**Extra return keys:**
- `solutions` (list[string]) — each solution as a SymPy string.
- `solutions_latex` (list[string]).
- `count` (int) — number of solutions; `-1` for an infinite family (with a representative in `solutions` and a describer in `assumptions`).

**Example:** critical points — first differentiate, then solve:
```json
{"equation": "3*x**2 - 12*x + 9", "variable": "x", "domain": "real"}
→ {"solutions": ["1", "3"], "count": 2, ...}
```

---

### `solve_ode`

Solve an ODE symbolically, optionally applying initial conditions.

**Parameters:**
- `equation` (string, required) — accepts prime notation `f'(x)`, `f''(x)` and explicit `Derivative(f(x), x, x)`.
- `function` (string, required) — name of the unknown, e.g. `"f"`. Must match what's used in `equation`.
- `variable` (string, required) — independent variable.
- `initial_conditions` (dict[string,string], optional) — e.g. `{"f(0)": "1", "f'(0)": "0"}`. IC keys must use the same function name as `function`.

**Assumptions field** includes the SymPy classification SymPy used (e.g. `"classified as: nth_linear_constant_coeff_homogeneous"`).

**Example:** simple-harmonic-oscillator IVP:
```json
{"equation": "f''(x) + f(x) = 0", "function": "f", "variable": "x",
 "initial_conditions": {"f(0)": "1", "f'(0)": "0"}}
→ {"result": "Eq(f(x), cos(x))", ...}
```

---

### `simplify_expression`

Rewrite an expression in one of six canonical forms.

**Parameters:**
- `expression` (string, required).
- `form` (`"simplify"` | `"expand"` | `"factor"` | `"collect"` | `"trigsimp"` | `"logcombine"`, required).
- `variable` (string, optional) — required when `form="collect"` (the variable to group by); ignored otherwise.

**Example:** Pythagorean identity:
```json
{"expression": "sin(x)**2 + cos(x)**2", "form": "simplify"}
→ {"result": "1", "is_exact": true, ...}
```

---

### `evaluate_numeric`

Substitute values and compute to high precision. Replaces LLM-hallucinated arithmetic.

**Parameters:**
- `expression` (string, required).
- `substitutions` (dict[string,string], optional) — values may themselves be SymPy expressions (`"sqrt(2)"`, `"pi/4"`).
- `precision` (int, optional, default `15`, max `50`) — significant decimal digits.

**Extra return keys:** `exact_form` — the post-substitution symbolic form before numerical evaluation.

**Agent aid:** if any key in `substitutions` doesn't match a symbol in the expression (typical agent typo), it's noted in `assumptions` as having had no effect.

**Example:** evaluate Taylor polynomial at a point:
```json
{"expression": "x**4/24 - x**2/2 + 1", "substitutions": {"x": "1/10"}}
→ {"result": "0.995004166666667", "exact_form": "238801/240000", ...}
```

---

## Quickstart

### Local development

```bash
# Install dependencies (creates .venv)
make install

# Run locally in STDIO mode with hot-reload
make run-local

# In another terminal, list tools with cmcp
cmcp ".venv/bin/python -m src.main" tools/list

# Call a tool
cmcp ".venv/bin/python -m src.main" tools/call differentiate \
  '{"expression": "x**2", "variables": ["x"]}'
```

### Testing

```bash
# Run the full test suite
make test

# Run tests for a single tool
.venv/bin/pytest tests/tools/test_integrate.py -v

# Run end-to-end tests (actual FastMCP server process)
.venv/bin/pytest tests/test_server_e2e.py -v
```

### Deploy to OpenShift

```bash
# One-time per deployment target
make deploy PROJECT=calculus-helper-mcp
```

The deploy uses OpenShift's internal image registry and BuildConfig — no local podman build required. The server runs on port 8080 inside the cluster with streamable-HTTP transport; the Route exposes `/mcp/` with TLS termination.

### Connect a client

For an MCP client pointing at a deployed instance:

```json
{
  "mcpServers": {
    "calculus-helper": {
      "url": "https://<route-host>/mcp/"
    }
  }
}
```

The trailing slash matters.

### System prompt for consuming agents

[`SYSTEM_PROMPT.md`](SYSTEM_PROMPT.md) is a ready-to-use system prompt for an LLM agent that will call these tools. It covers the "always use the tool, never compute in-head" discipline, the shared return-dict contract, per-tool usage guidance, composition patterns, an error-recovery table mapping each coaching message to the fix, and worked examples. Drop it into your agent's system role (or adapt it) — it's grounded in what the tools actually do, not generic math-assistant boilerplate.

## Project layout

```
src/
  core/
    server.py     # create_server() + run_server(): providers, middleware, auth
    auth.py       # Optional JWT auth via FastMCP's JWTVerifier
    logging.py
  tools/
    differentiate.py, integrate.py, evaluate_limit.py, taylor_series.py,
    solve_equation.py, solve_ode.py, simplify_expression.py, evaluate_numeric.py
  calc.py         # Shared parsing + output-dict formatting for all 8 tools
  main.py         # Entry point: creates server, runs selected transport
tests/
  tools/          # Per-tool unit tests (74 tests)
  test_server_e2e.py    # Full FastMCP-client end-to-end tests
  test_server.py, test_auth*.py  # Infrastructure tests
Containerfile, openshift.yaml, deploy.sh, Makefile
```

All 8 tools delegate their parsing and result-formatting to `src/calc.py`. This centralizes the restricted-namespace parser (which deliberately excludes SymPy's `split_symbols` transformer to avoid silently shredding multi-letter names like `log10` into `l*o*g*10`) and the standard return-dict contract.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` (local) or `http` (OpenShift, set in the Containerfile). |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP bind address. |
| `MCP_HTTP_PORT` | `8000` | HTTP port (8080 in-container). |
| `MCP_HTTP_PATH` | `/mcp/` | HTTP endpoint path. |
| `MCP_LOG_LEVEL` | `INFO` | Logging level. |
| `MCP_HOT_RELOAD` | `0` | `1` enables `FileSystemProvider` watch-and-reload for dev. |

JWT auth is configurable via `MCP_AUTH_JWT_*` variables; see `src/core/auth.py`. Auth is disabled when no `MCP_AUTH_JWT_ALG` is set.

## Adding another tool

If you need a ninth tool, scaffold it with:

```bash
fips-agents generate tool my_tool --description "..." --async --with-context
```

This creates `src/tools/my_tool.py` plus a test scaffold in `tests/tools/`. Import the shared helpers from `src/calc.py` — do not call `sp.sympify()` directly on user strings:

```python
from src.calc import parse_expression, parse_symbol, format_result
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full request/response flow and design decisions.

## Requirements

- Python 3.11+
- OpenShift CLI (`oc`) for deployment
- `cmcp` for local STDIO testing (`pip install cmcp`)

## License

MIT. See [LICENSE](LICENSE).
