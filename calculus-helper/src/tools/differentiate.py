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
                "['x'] → df/dx.  ['x', 'x'] → d²f/dx² (repeat for higher order). "
                "['x', 'y'] → mixed partial ∂²f/∂x∂y."
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

    # Parse each differentiation variable; free symbols in the expression for warning check.
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

    # Compute the derivative.  sp.diff(expr, x, y) gives ∂²/∂x∂y.
    derivative = sp.diff(expr, *symbols)

    # Evaluate at a point if requested.
    if at_point is not None:
        subs = parse_substitutions(at_point, context="at_point")
        # Warn for substitution variables absent from the original expression.
        for sym in subs:
            if str(sym) not in expr_free_syms:
                assumptions.append(
                    f"'{sym}' not present in expression; substitution has no effect"
                )
        derivative = derivative.subs(subs)
        # Light simplification — just evaluate unevaluated objects without the
        # cost of sp.simplify().
        derivative = derivative.doit()

    return format_result(derivative, assumptions=assumptions)
