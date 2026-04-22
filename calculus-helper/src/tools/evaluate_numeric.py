"""Substitute values into an expression and compute a numerical result to specified precision."""

from typing import Annotated

import sympy as sp
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from pydantic import Field

from src.calc import format_result, parse_expression, parse_substitutions

_MAX_PRECISION = 50
_DEFAULT_PRECISION = 15


@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def evaluate_numeric(
    expression: Annotated[
        str,
        Field(description="Expression to evaluate, e.g. 'sqrt(pi)*erf(1)/2'"),
    ],
    substitutions: Annotated[
        dict[str, str] | None,
        Field(
            description=(
                "Optional map from variable name to value expression, "
                "e.g. {\"x\": \"2\", \"y\": \"pi/4\"}. Values may themselves be "
                "SymPy expressions such as 'sqrt(2)' or 'pi/3'."
            )
        ),
    ] = None,
    precision: Annotated[
        int,
        Field(
            description=(
                f"Significant decimal digits in the result (default {_DEFAULT_PRECISION}, max {_MAX_PRECISION})."
            ),
            ge=1,
        ),
    ] = _DEFAULT_PRECISION,
    ctx: Context = None,
) -> dict:
    """Substitute concrete values and compute a high-precision numerical result.

    Parses the expression and optional substitutions symbolically, applies the
    substitutions, checks that no free variables remain, then evaluates to the
    requested number of significant digits via SymPy's arbitrary-precision
    engine. Returns both the numerical result and the pre-evaluation exact form.
    """
    if ctx is not None:
        await ctx.info(
            f"evaluate_numeric: precision={precision} subs={substitutions!r} expression={expression!r}"
        )

    if precision > _MAX_PRECISION:
        raise ToolError(
            f"Max precision is {_MAX_PRECISION} digits. "
            "For higher precision, restructure the expression to isolate the sensitive term "
            "and call again with a lower-precision outer evaluation."
        )

    expr = parse_expression(expression, context="expression")
    pre_subs_symbols = {str(s) for s in expr.free_symbols}

    subs = parse_substitutions(substitutions, context="substitutions")
    if subs:
        expr = expr.subs(subs)

    # Warn on substitutions that didn't match any variable in the expression --
    # usually indicates a typo in the substitution key.
    unused = sorted(str(s) for s in subs if str(s) not in pre_subs_symbols)

    free = expr.free_symbols
    if free:
        names = ", ".join(sorted(str(s) for s in free))
        hint = ""
        if unused:
            hint = (
                f" Note: the substitution(s) for {unused} were unused "
                "(those names are not in the expression) -- check for a typo."
            )
        raise ToolError(
            f"Expression still has free variable(s) after substitution: {names}. "
            "Add them to 'substitutions' before calling evaluate_numeric." + hint
        )

    # Capture the exact symbolic form before converting to float.
    exact_form = str(expr)

    numerical = sp.N(expr, precision)

    assumptions: list[str] = []
    if subs:
        assumptions.append("Substituted before evaluation")
    if unused:
        assumptions.append(
            f"substitutions for {unused} had no effect (names not in expression)"
        )

    return format_result(
        numerical,
        assumptions=assumptions,
        extra={"exact_form": exact_form},
    )
