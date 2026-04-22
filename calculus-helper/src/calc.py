"""Shared parsing and formatting helpers for the calculus tools.

All calculus tools use SymPy for symbolic math. This module centralises the
cross-cutting concerns so every tool behaves consistently:

- ``parse_expression`` -- parse a user string into a SymPy expression using a
  restricted whitelist namespace (no arbitrary Python ``eval``), with
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

# Whitelisted names available inside parsed expressions.  Anything not in this
# dict (e.g. ``eval``, ``__import__``, file IO) is inaccessible.  Free names
# that look like identifiers (``x``, ``theta``) become fresh SymPy ``Symbol``
# instances automatically.
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
    "ln": sp.log,
    "log10": lambda x: sp.log(x, 10),
    "log2": lambda x: sp.log(x, 2),
    "sqrt": sp.sqrt,
    "cbrt": sp.cbrt,
    # Inverse trig — accept both `asin` and `arcsin` spellings.
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

# Deliberately DO NOT include ``split_symbols`` here.  It would rewrite
# ``log10(x)`` as ``l*o*g*10*x``, silently producing wrong answers that look
# superficially like expressions.  We use ``implicit_multiplication`` (so
# ``2x`` still means ``2*x``) and ``implicit_application`` without the
# letter-level split.  Multi-letter identifiers not in the whitelist become a
# single ``Symbol`` — still not what the user wanted, but the mistake is now
# visible rather than silent.
_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication,
    implicit_application,
)


def parse_expression(expr_str: str, *, context: str = "expression") -> sp.Expr:
    """Parse a user-supplied expression string into a SymPy expression.

    The parser uses a restricted namespace so arbitrary Python code cannot be
    evaluated.  Identifiers not on the whitelist become fresh SymPy symbols.

    Args:
        expr_str: The expression to parse, e.g. ``"sin(x) * exp(-x)"``.
        context: Short label for error messages
            (e.g. ``"integrand"``, ``"lower bound"``).  Appears in
            ``ToolError`` messages to help the agent locate the bad input.

    Raises:
        ToolError: With coaching text for common mistakes (``^`` instead of
            ``**``, unbalanced parentheses, unknown function names, ...).
    """
    if not isinstance(expr_str, str):
        raise ToolError(
            f"Expected a string for {context}, got {type(expr_str).__name__}."
        )
    stripped = expr_str.strip()
    if not stripped:
        raise ToolError(f"{context} cannot be empty.")

    # Coach on the most common mistake BEFORE the parser silently mis-reads it.
    # In Python/SymPy, ``^`` is bitwise XOR, not exponentiation.  ``2^3``
    # parses as ``2 XOR 3 == 1`` rather than ``8``, which is a near-invisible
    # bug.  Reject it with a clear explanation.
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
    """Parse a variable name into a SymPy ``Symbol``.

    Accepts a bare identifier (``"x"``, ``"theta"``, ``"t_1"``).  Anything
    else -- expressions, numbers, whitespace, operators -- is rejected with a
    ``ToolError`` so the agent knows the slot expects a name, not an
    expression.
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
    """Parse ``{var_name: value_expression}`` strings into SymPy form.

    Values are themselves expressions, so callers can pass ``"sqrt(2)"`` or
    ``"pi/4"`` as substitution targets -- not just bare numbers.
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
    """Return ``True`` when ``expr`` is a symbolic / exact SymPy object.

    The heuristic is "contains no ``sympy.Float``".  Rational numbers,
    radicals, trig at exact angles, ``oo``, and ``nan`` are all considered
    exact.  Anything produced by ``evalf`` / ``sp.N`` generally contains
    ``Float`` and is reported as approximate.
    """
    try:
        basic = expr if isinstance(expr, sp.Basic) else sp.sympify(expr)
    except (sp.SympifyError, TypeError):
        # Non-symbolic scalars (plain int/str labels) are treated as exact.
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

    Args:
        expr: The SymPy expression (or any ``sympify``-able value) to format.
        assumptions: Free-form notes about assumptions SymPy applied while
            computing (e.g. "x assumed real", "integration constant omitted").
            Agents surface these to the user verbatim.
        extra: Additional keys to merge into the returned dict, for tools
            whose response shape extends the standard (e.g. ``solve_equation``
            adds ``solutions`` and ``count``).

    Returns:
        Dict with ``result`` (str), ``latex`` (str), ``is_exact`` (bool),
        ``assumptions`` (list[str]), plus any keys from ``extra``.
    """
    if assumptions is None:
        assumptions = []

    if isinstance(expr, sp.Basic):
        sympy_expr: sp.Basic = expr
    else:
        try:
            sympy_expr = sp.sympify(expr)
        except (sp.SympifyError, TypeError):
            # Fall back to str() for opaque values -- e.g. a dict result.
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
