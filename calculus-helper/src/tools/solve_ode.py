"""Solve ordinary differential equations symbolically, with optional initial conditions."""

import re
from tokenize import TokenError
from typing import Annotated, Any

import sympy as sp
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from pydantic import Field
from sympy.parsing.sympy_parser import (
    implicit_application,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

from src.calc import format_result, parse_expression, parse_symbol

# Matches the transformation tuple in ``src/calc.py`` — deliberately excludes
# ``split_symbols`` to avoid silently mangling multi-letter names like
# ``log10`` or ``arcsin`` into products of individual letters.
_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication,
    implicit_application,
)

# ---------------------------------------------------------------------------
# Base safe namespace (same whitelist as calc.py, no mutation of the original)
# ---------------------------------------------------------------------------
_BASE_ODE_NAMESPACE: dict[str, Any] = {
    "pi": sp.pi,
    "E": sp.E,
    "I": sp.I,
    "oo": sp.oo,
    "inf": sp.oo,
    "infinity": sp.oo,
    "nan": sp.nan,
    "NaN": sp.nan,
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
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "asinh": sp.asinh,
    "acosh": sp.acosh,
    "atanh": sp.atanh,
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    "log10": lambda x: sp.log(x, 10),
    "log2": lambda x: sp.log(x, 2),
    "sqrt": sp.sqrt,
    "cbrt": sp.cbrt,
    "arcsin": sp.asin,
    "arccos": sp.acos,
    "arctan": sp.atan,
    "arctan2": sp.atan2,
    "arcsinh": sp.asinh,
    "arccosh": sp.acosh,
    "arctanh": sp.atanh,
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
    "Derivative": sp.Derivative,
    "Function": sp.Function,
    "Eq": sp.Eq,
}


def _parse_ode_expr(expr_str: str, func_sym: sp.Function, var_sym: sp.Symbol,
                    *, context: str = "expression") -> sp.Expr:
    """Parse an ODE expression string with the function and variable in namespace.

    This is needed because the shared ``parse_expression`` in calc.py doesn't
    accept extra namespace entries. The ODE parser augments the whitelist with
    the unknown function (e.g. ``f``) and the independent variable (e.g. ``x``)
    so that ``Derivative(f(x), x)`` and ``f(x)`` parse correctly.

    Args:
        expr_str: Expression string to parse.
        func_sym: The SymPy Function class for the unknown, e.g. ``sp.Function('f')``.
        var_sym: The independent variable Symbol, e.g. ``sp.Symbol('x')``.
        context: Label for error messages.

    Raises:
        ToolError: On parse failure, with coaching text.
    """
    if not isinstance(expr_str, str):
        raise ToolError(f"Expected a string for {context}, got {type(expr_str).__name__}.")
    stripped = expr_str.strip()
    if not stripped:
        raise ToolError(f"{context} cannot be empty.")

    if "^" in stripped:
        raise ToolError(
            f"Invalid {context}: '{stripped}'. Use '**' for exponents, not '^'. "
            "In Python/SymPy '^' is bitwise XOR."
        )

    func_name = str(func_sym)
    var_name = str(var_sym)

    local_dict = dict(_BASE_ODE_NAMESPACE)
    local_dict[func_name] = sp.Function(func_name)
    local_dict[var_name] = var_sym

    try:
        return parse_expr(stripped, local_dict=local_dict, transformations=_TRANSFORMATIONS)
    except (SyntaxError, TokenError, ValueError, TypeError, NameError) as e:
        raise ToolError(
            f"Could not parse {context}: '{stripped}'. "
            f"Parser said: {type(e).__name__}: {e}. "
            "Check for balanced parentheses. Use '**' for exponents, '*' for "
            "multiplication, and Python-style function names "
            "(sin, cos, exp, log, sqrt). "
            "Use 'pi' for pi, 'E' for Euler's constant, 'oo' for infinity."
        )


def _normalize_derivative_shorthands(eq_str: str) -> str:
    """Convert prime-notation shorthands to SymPy Derivative form.

    Transforms ``f'(x)`` → ``Derivative(f(x), x)``,
    ``f''(x)`` → ``Derivative(f(x), x, x)``, and so on.
    Already-normalized ``Derivative(...)`` forms pass through unchanged.

    Args:
        eq_str: Raw ODE string that may contain prime notation.

    Returns:
        String with all prime shorthands replaced by Derivative calls.
    """

    def _replace(m: re.Match) -> str:
        fname = m.group(1)
        primes = m.group(2)
        arg = m.group(3)
        order = len(primes)
        vars_str = ", ".join([arg] * order)
        return f"Derivative({fname}({arg}), {vars_str})"

    # Pattern: identifier + one-or-more apostrophes + (arg)
    # e.g. f'(x), f''(x), g'''(t)
    return re.sub(r"(\w+)('+'?)(\([^)]+\))", _replace, eq_str)


def _parse_ode_equation(
    eq_str: str, func_sym: sp.Function, var_sym: sp.Symbol
) -> sp.Eq:
    """Parse an ODE string (after shorthand normalization) into a SymPy Eq.

    Handles both ``lhs = rhs`` and bare expression (implicitly = 0) forms.
    Raises ToolError on parse failure or multiple ``=`` signs.
    """
    eq_count = eq_str.count("=")
    double_eq_count = eq_str.count("==")
    single_eq_count = eq_count - 2 * double_eq_count

    if single_eq_count > 1:
        raise ToolError(
            f"Invalid ODE equation: '{eq_str}'. "
            "Use exactly one '=' separator, e.g. \"f''(x) + f(x) = 0\"."
        )

    if single_eq_count == 1:
        placeholder = "\x00eq\x00"
        sanitized = eq_str.replace("==", placeholder)
        parts = sanitized.split("=", 1)
        lhs_str = parts[0].replace(placeholder, "==").strip()
        rhs_str = parts[1].replace(placeholder, "==").strip()
        lhs = _parse_ode_expr(lhs_str, func_sym, var_sym, context="ODE left-hand side")
        rhs = _parse_ode_expr(rhs_str, func_sym, var_sym, context="ODE right-hand side")
        return sp.Eq(lhs, rhs)
    else:
        expr = _parse_ode_expr(eq_str, func_sym, var_sym, context="ODE equation")
        return sp.Eq(expr, 0)


def _parse_ics(
    initial_conditions: dict[str, str],
    func_name: str,
    var_sym: sp.Symbol,
) -> dict:
    """Parse initial condition dict into SymPy form for dsolve's ``ics`` parameter.

    Keys like ``"f(0)"`` become ``f(0)`` and keys like ``"f'(0)"`` become
    ``Subs(Derivative(f(x), x), x, 0)`` — exactly what dsolve expects.

    Args:
        initial_conditions: Raw string dict, e.g. ``{"f(0)": "1", "f'(0)": "0"}``.
        func_name: The function name, e.g. ``"f"``.
        var_sym: The independent variable symbol.

    Returns:
        Dict mapping SymPy IC keys to SymPy values, ready for dsolve.

    Raises:
        ToolError: If a key or value can't be parsed.
    """
    f = sp.Function(func_name)
    x = var_sym
    ics: dict = {}

    # Pattern for IC keys: funcname + optional primes + (arg)
    key_pattern = re.compile(r"^(\w+)('*)(\([^)]+\))$")

    for key_str, val_str in initial_conditions.items():
        key_stripped = key_str.strip()
        m = key_pattern.match(key_stripped)
        if not m:
            raise ToolError(
                f"Cannot parse initial condition key '{key_str}'. "
                "Expected forms like 'f(0)' or \"f'(0)\". "
                "Use apostrophes for derivatives, e.g. \"f''(0)\" for second derivative."
            )

        ic_func_name = m.group(1)
        if ic_func_name != func_name:
            raise ToolError(
                f"Initial condition key '{key_str}' refers to function "
                f"'{ic_func_name}', but the ODE is being solved for function "
                f"'{func_name}'. Use keys like '{func_name}(0)' or "
                f"\"{func_name}'(0)\", or correct the `function` parameter."
            )

        primes = m.group(2)
        arg_str = m.group(3)[1:-1]  # strip outer parens
        order = len(primes)

        try:
            arg_val = sp.sympify(arg_str)
        except (sp.SympifyError, TypeError) as e:
            raise ToolError(
                f"Cannot parse argument '{arg_str}' in IC key '{key_str}': {e}."
            )

        if order == 0:
            ic_key = f(arg_val)
        else:
            # Derivative evaluated at arg_val
            ic_key = f(x).diff(x, order).subs(x, arg_val)

        ic_val = parse_expression(
            val_str, context=f"initial condition value for '{key_str}'"
        )
        ics[ic_key] = ic_val

    return ics


@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def solve_ode(
    equation: Annotated[
        str,
        Field(
            description=(
                "ODE in Python/SymPy syntax. Accepts prime shorthand: "
                "\"f'(x) - f(x) = 0\" or \"f''(x) + f(x) = 0\". "
                "Also accepts explicit Derivative notation: "
                "\"Derivative(f(x), x) - f(x) = 0\". "
                "Use '**' for exponents."
            )
        ),
    ],
    function: Annotated[
        str,
        Field(
            description=(
                "Name of the unknown function, e.g. 'f'. "
                "Must match the function name used in the equation."
            )
        ),
    ],
    variable: Annotated[
        str,
        Field(
            description=(
                "Independent variable, e.g. 'x'. "
                "Must match the variable used in the equation."
            )
        ),
    ],
    initial_conditions: Annotated[
        dict[str, str] | None,
        Field(
            description=(
                "Optional initial value conditions as a dict from condition to value. "
                "Examples: {'f(0)': '1'} or {\"f(0)\": \"1\", \"f'(0)\": \"0\"}. "
                "Keys use prime notation for derivatives. Values are SymPy expressions."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> dict:
    """Solve an ordinary differential equation symbolically, with optional initial conditions.

    Accepts ODEs in prime notation (f'(x)) or explicit Derivative form. Returns the
    general solution (with constants C1, C2, ...) or the particular solution when
    initial conditions are provided. Includes SymPy's ODE classification in assumptions.
    """
    if ctx is not None:
        await ctx.info(
            f"solve_ode: equation={equation!r} function={function!r} "
            f"variable={variable!r} initial_conditions={initial_conditions!r}"
        )

    var_sym = parse_symbol(variable, context="variable")
    func_sym = sp.Function(parse_symbol(function, context="function").name)

    # Normalize f'(x) -> Derivative(f(x), x) before parsing.
    normalized = _normalize_derivative_shorthands(equation)

    eq = _parse_ode_equation(normalized, func_sym, var_sym)

    # Reconstruct the function expression f(x) for dsolve.
    func_expr = func_sym(var_sym)

    # Classify the ODE for the assumptions field.
    assumptions: list[str] = []
    try:
        classifications = sp.classify_ode(eq, func_expr)
        if classifications:
            assumptions.append(f"classified as: {classifications[0]}")
    except Exception:
        pass  # Classification is advisory; don't fail if it errors.

    # Parse initial conditions if provided.
    ics: dict | None = None
    if initial_conditions:
        ics = _parse_ics(initial_conditions, str(func_sym), var_sym)

    # Solve.
    try:
        if ics:
            solution = sp.dsolve(eq, func_expr, ics=ics)
        else:
            solution = sp.dsolve(eq, func_expr)
    except NotImplementedError as e:
        raise ToolError(
            "This ODE's form isn't in SymPy's solvable classes. "
            "Consider: (1) simplifying, (2) asking for a series solution via "
            "`taylor_series` on an assumed form, (3) numerical methods which "
            "this server doesn't currently provide."
        ) from e
    except Exception as e:
        raise ToolError(
            f"SymPy could not solve the ODE: {e}. "
            "Check that the equation and function/variable names are consistent."
        ) from e

    return format_result(solution, assumptions=assumptions)
