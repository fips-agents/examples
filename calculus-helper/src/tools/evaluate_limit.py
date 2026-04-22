"""Compute limits at a point or at infinity, from either side or two-sided."""

from typing import Annotated, Literal

import sympy as sp
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from pydantic import Field

from src.calc import format_result, parse_expression, parse_symbol

# SymPy's sp.oo as a string so we can compare parsed points
_INFINITY_POINTS = {sp.oo, -sp.oo}


@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def evaluate_limit(
    expression: Annotated[
        str,
        Field(
            description=(
                "Expression whose limit to compute, in Python/SymPy syntax. "
                "e.g. 'sin(x)/x', '(1 - cos(x))/x**2'. Use '**' not '^' for exponents."
            )
        ),
    ],
    variable: Annotated[
        str,
        Field(description="The variable approaching the limit point, e.g. 'x'."),
    ],
    point: Annotated[
        str,
        Field(
            description=(
                "The limit point. Use 'oo' for +∞, '-oo' for −∞, "
                "or any SymPy expression like '0', 'pi/2', 'E'."
            )
        ),
    ],
    direction: Annotated[
        Literal["left", "right", "both"],
        Field(
            description=(
                "Direction of approach. "
                "'left' = x → point from below (x → point⁻). "
                "'right' = x → point from above (x → point⁺). "
                "'both' = two-sided limit (default). "
                "Ignored when point is ±∞."
            )
        ),
    ] = "both",
    ctx: Context = None,
) -> dict:
    """Compute the limit of an expression as a variable approaches a point.

    Handles finite points, ±∞, and one-sided limits. For two-sided limits
    at finite points, computes both one-sided limits and returns 'nan' with
    an explanation if they disagree. Returns result in both plain-text and
    LaTeX, with is_exact=True for symbolic results.
    """
    if ctx is not None:
        await ctx.info(
            f"evaluate_limit: expression={expression!r} variable={variable!r} "
            f"point={point!r} direction={direction!r}"
        )

    expr = parse_expression(expression, context="expression")
    sym = parse_symbol(variable, context="variable")
    pt = parse_expression(point, context="point")

    assumptions: list[str] = []

    # -----------------------------------------------------------------------
    # Infinity: direction is not meaningful — SymPy handles it directly.
    # Always add a note so the caller knows direction was disregarded.
    # -----------------------------------------------------------------------
    if pt in _INFINITY_POINTS:
        assumptions.append(
            "direction ignored: approaching infinity has no left/right concept"
        )
        limit_val = sp.limit(expr, sym, pt)
        return format_result(limit_val, assumptions=assumptions)

    # -----------------------------------------------------------------------
    # Finite point with explicit direction.
    # -----------------------------------------------------------------------
    if direction == "left":
        limit_val = sp.limit(expr, sym, pt, "-")
        return format_result(limit_val, assumptions=assumptions)

    if direction == "right":
        limit_val = sp.limit(expr, sym, pt, "+")
        return format_result(limit_val, assumptions=assumptions)

    # -----------------------------------------------------------------------
    # Two-sided limit: compute both sides and compare.
    #
    # We do NOT rely on sp.limit(..., dir="+-") because its behaviour varies
    # between SymPy versions — some versions return the right-hand limit when
    # the two sides disagree instead of raising or returning nan.  The only
    # reliable approach is to compute both one-sided limits and compare them.
    # -----------------------------------------------------------------------
    left_val = sp.limit(expr, sym, pt, "-")
    right_val = sp.limit(expr, sym, pt, "+")

    if left_val == right_val:
        return format_result(left_val, assumptions=assumptions)

    # One-sided limits disagree — two-sided limit does not exist.
    assumptions.append(
        f"left limit is {left_val}, right limit is {right_val}; "
        "two-sided limit does not exist"
    )
    return format_result(sp.nan, assumptions=assumptions)
