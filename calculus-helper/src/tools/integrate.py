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
                "Use '-oo' for −∞, or any SymPy expression like '0', 'pi', 'exp(1)'. "
                "Must be provided together with upper_bound, or omitted for indefinite."
            )
        ),
    ] = None,
    upper_bound: Annotated[
        str | None,
        Field(
            description=(
                "Upper limit for a definite integral. "
                "Use 'oo' for +∞, or any SymPy expression like '1', 'pi', 'sqrt(2)'. "
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
    of the swapped integral, following the standard convention ∫[a,b] f = −∫[b,a] f.
    This is mathematically correct, NOT a bug. If you pass bounds in unintended order
    the sign of the answer will flip -- double-check bound order before trusting a
    negative result from a non-negative integrand.
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
        # Caller explicitly asked for numerical — skip symbolic entirely.
        num_result = sp.Integral(expr, (sym, low, high)).evalf()
        return format_result(num_result, assumptions=assumptions)

    # Symbolic attempt first.
    result = sp.integrate(expr, (sym, low, high))

    # If SymPy returned an unevaluated Integral, fall back to numerical.
    if isinstance(result, sp.Integral):
        num_result = result.evalf()
        return format_result(num_result, assumptions=assumptions)

    # Divergent result — valid symbolic answer, just note it.
    if result in (sp.oo, -sp.oo, sp.zoo):
        assumptions.append("integral diverges")

    return format_result(result, assumptions=assumptions)
