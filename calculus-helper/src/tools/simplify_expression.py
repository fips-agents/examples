"""Rewrite a symbolic expression using simplify/expand/factor/collect/trigsimp/logcombine."""

from typing import Annotated, Literal

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
async def simplify_expression(
    expression: Annotated[
        str,
        Field(description="Expression to transform, e.g. 'sin(x)**2 + cos(x)**2'"),
    ],
    form: Annotated[
        Literal["simplify", "expand", "factor", "collect", "trigsimp", "logcombine"],
        Field(
            description=(
                "Which rewrite to apply: 'simplify' (heuristic), 'expand' (distribute products), "
                "'factor' (factor polynomials), 'collect' (group by variable — requires 'variable'), "
                "'trigsimp' (simplify trig expressions), 'logcombine' (combine/expand logarithms)."
            )
        ),
    ],
    variable: Annotated[
        str | None,
        Field(
            description="Required when form='collect' — the variable to group by, e.g. 'x'. Ignored for other forms."
        ),
    ] = None,
    ctx: Context = None,
) -> dict:
    """Rewrite a symbolic expression using the requested canonical form.

    Applies one of six SymPy rewriting strategies to a user-supplied expression.
    Returns the transformed expression in both plain-text (SymPy-safe to re-parse)
    and LaTeX form.
    """
    if ctx is not None:
        await ctx.info(f"simplify_expression: form={form!r} expression={expression!r}")

    # Validate collect prerequisite before parsing anything.
    if form == "collect" and not variable:
        raise ToolError(
            "`collect` requires a `variable` parameter — which variable to group by?"
        )

    expr = parse_expression(expression, context="expression")

    if form == "simplify":
        result = sp.simplify(expr)
    elif form == "expand":
        result = sp.expand(expr)
    elif form == "factor":
        result = sp.factor(expr)
    elif form == "collect":
        sym = parse_symbol(variable, context="variable")
        result = sp.collect(expr, sym)
    elif form == "trigsimp":
        result = sp.trigsimp(expr)
    elif form == "logcombine":
        result = sp.logcombine(expr, force=True)
    else:
        # Defensive guard: Literal typing blocks this on the normal dispatch
        # path, but a direct Python call can bypass Pydantic validation.
        raise ToolError(
            f"Unknown form {form!r}. Valid forms: "
            "'simplify', 'expand', 'factor', 'collect', 'trigsimp', 'logcombine'."
        )

    return format_result(result)
