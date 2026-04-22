"""Compute Taylor series expansion of an expression around a point up to a given order."""

from typing import Annotated

import sympy as sp
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from pydantic import Field

from src.calc import format_result, parse_expression, parse_symbol

# Hard limit to prevent runaway computation from high-order series requests.
_MAX_ORDER = 20


def _extract_coefficients(
    series_no_o: sp.Expr,
    sym: sp.Symbol,
    around_pt: sp.Expr,
    order: int,
) -> list[str]:
    """Extract Taylor coefficients for powers 0 through order-1.

    For a series expanded around a point `a`, the k-th coefficient is the
    coefficient of `(sym - a)^k` in the truncated polynomial.  We extract
    this by substituting `u = sym - a` (i.e. shifting to 0) and then using
    SymPy's polynomial `coeff()`.
    """
    # Shift the expansion to be centred at 0 so coeff(u, k) works cleanly.
    # Replace `sym` with `u + around_pt` in the already-removed-O expression.
    u = sp.Dummy("u")
    shifted = series_no_o.subs(sym, u + around_pt)
    shifted_expanded = sp.expand(shifted)

    coeffs = []
    for k in range(order):
        c = shifted_expanded.coeff(u, k)
        coeffs.append(str(c))
    return coeffs


@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def taylor_series(
    expression: Annotated[
        str,
        Field(
            description=(
                "Function to expand, in Python/SymPy syntax. "
                "e.g. 'sin(x)', 'exp(x)', 'log(1 + x)'. Use '**' not '^' for exponents."
            )
        ),
    ],
    variable: Annotated[
        str,
        Field(description="Variable for the series expansion, e.g. 'x'."),
    ],
    around: Annotated[
        str,
        Field(
            description=(
                "Point of expansion. '0' gives a Maclaurin series (default). "
                "Any SymPy expression is accepted, e.g. '1', 'pi', 'E'."
            )
        ),
    ] = "0",
    order: Annotated[
        int,
        Field(
            description=(
                "Number of terms to compute (truncation order). "
                "The series is computed up to O(variable**order). Min 1, max 20."
            ),
            ge=1,
            le=_MAX_ORDER,
        ),
    ] = 6,
    ctx: Context = None,
) -> dict:
    """Compute the Taylor (Maclaurin) series expansion of an expression.

    Returns the truncated polynomial in both plain-text and LaTeX forms,
    plus a list of per-term coefficients (powers 0 through order-1) so agents
    can reason about individual terms. Raises ToolError if the function is not
    analytic at the expansion point (e.g. 1/x around 0).
    """
    if ctx is not None:
        await ctx.info(
            f"taylor_series: expression={expression!r} variable={variable!r} "
            f"around={around!r} order={order!r}"
        )

    # Belt-and-suspenders order check — Pydantic's le=20 handles the normal
    # path, but this guard catches any bypass (e.g. direct Python call in tests
    # or a future change that removes the Field constraint).
    if order > _MAX_ORDER:
        raise ToolError(
            f"Orders above {_MAX_ORDER} are rejected to prevent runaway computation. "
            "Request a lower order, or call differentiate repeatedly if you need "
            "specific higher-order coefficients."
        )

    expr = parse_expression(expression, context="expression")
    sym = parse_symbol(variable, context="variable")
    around_pt = parse_expression(around, context="around")

    # Compute the series.
    try:
        series_result = sp.series(expr, sym, around_pt, order)
    except (ValueError, TypeError, sp.PoleError, NotImplementedError) as exc:
        raise ToolError(
            f"Function is not analytic at {around}: SymPy raised {type(exc).__name__}: {exc}. "
            "Try a different expansion point or check for a singularity."
        ) from exc

    # Detect failure modes:
    # 1. SymPy returns an expression without an O() term — expansion failed
    #    (e.g. log(x) around 0 just returns log(x) unchanged).
    # 2. The removed-O result contains negative powers of the variable —
    #    a Laurent series, meaning the function has a pole at the given point.
    series_o = series_result.getO()
    if series_o is None:
        raise ToolError(
            f"Function is not analytic at {around}: SymPy could not produce a "
            "Taylor series at this point. Check for a singularity or branch point."
        )

    series_no_o = series_result.removeO()

    # Check for negative powers (Laurent series / pole at expansion point).
    shift = sym - around_pt
    for subexpr in sp.preorder_traversal(series_no_o):
        if isinstance(subexpr, sp.Pow):
            base, exp_val = subexpr.args
            if base in (sym, shift) and exp_val.is_negative:
                raise ToolError(
                    f"Function is not analytic at {around}: the series contains "
                    f"negative powers ({subexpr}), indicating a pole. "
                    "Try a different expansion point."
                )

    # Extract per-power coefficients.
    coefficients = _extract_coefficients(series_no_o, sym, around_pt, order)

    return format_result(
        series_no_o,
        assumptions=[],
        extra={"coefficients": coefficients},
    )
