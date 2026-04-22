"""Find symbolic or numerical roots of an equation, optionally restricted to a domain."""

from typing import Annotated, Literal

import sympy as sp
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from pydantic import Field
from sympy.sets.conditionset import ConditionSet
from sympy.sets.sets import EmptySet, FiniteSet

from src.calc import format_result, parse_expression, parse_symbol


def _parse_equation(equation: str) -> sp.Eq:
    """Parse an equation string into a SymPy Eq object.

    Accepts two forms:
    - ``"lhs = rhs"`` — split on ``=`` and parse each side.
    - ``"expr"`` — treat as ``expr = 0``.

    Raises ToolError for multiple ``=`` signs or parse failures.
    """
    # Check for ``=`` (the equation form) but be careful about ``==``.
    # We treat a single ``=`` as the equation separator.  Multiple ``=``
    # signs (other than ``==``) are an error.
    eq_count = equation.count("=")
    double_eq_count = equation.count("==")
    single_eq_count = eq_count - 2 * double_eq_count  # == contributes 2 to count

    if single_eq_count > 1:
        raise ToolError(
            f"Invalid equation: '{equation}'. "
            "Exactly one '=' separator is allowed (e.g. 'x**2 = 4'). "
            f"Found {single_eq_count} single '=' signs. "
            "If you meant to compare equality, use a single '=' to separate LHS and RHS."
        )

    if single_eq_count == 1:
        # Split on the single =, being careful not to split on ==.
        # Replace == with a placeholder, split on =, restore.
        placeholder = "\x00eq\x00"
        sanitized = equation.replace("==", placeholder)
        parts = sanitized.split("=", 1)
        if len(parts) != 2:
            raise ToolError(
                f"Could not split equation '{equation}' on '='. "
                "Use the form 'lhs = rhs', e.g. 'x**2 = 4'."
            )
        lhs_str = parts[0].replace(placeholder, "==").strip()
        rhs_str = parts[1].replace(placeholder, "==").strip()
        lhs = parse_expression(lhs_str, context="equation left-hand side")
        rhs = parse_expression(rhs_str, context="equation right-hand side")
        return sp.Eq(lhs, rhs)
    else:
        # Expression form: treat as expr = 0.
        expr = parse_expression(equation, context="equation")
        return sp.Eq(expr, 0)


@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def solve_equation(
    equation: Annotated[
        str,
        Field(
            description=(
                "Equation to solve. Either an explicit equation like 'x**2 - 4 = 0' "
                "or an expression implicitly set equal to zero like 'x**2 - 4'. "
                "Use Python/SymPy syntax: '**' for exponents, 'sin', 'cos', 'exp', etc."
            )
        ),
    ],
    variable: Annotated[
        str,
        Field(
            description=(
                "Variable to solve for, e.g. 'x'. Must be a simple identifier."
            )
        ),
    ],
    domain: Annotated[
        Literal["real", "complex", "positive"],
        Field(
            description=(
                "Solution domain. "
                "'complex' (default) — all complex solutions. "
                "'real' — only real-valued solutions. "
                "'positive' — only strictly positive real solutions."
            )
        ),
    ] = "complex",
    numerical_near: Annotated[
        str | None,
        Field(
            description=(
                "If provided, use numerical root-finding seeded near this value "
                "(e.g. '1.5'). Use for transcendental equations where symbolic "
                "solving fails. Returns one solution."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> dict:
    """Find symbolic or numerical roots of an equation, optionally restricted to a domain.

    Accepts an equation ('lhs = rhs') or an expression ('expr', solved as expr = 0).
    Returns all solutions in the requested domain. For infinite solution families
    (e.g. sin(x) = 0), sets count=-1. Falls back to numerical root-finding when
    numerical_near is supplied.
    """
    if ctx is not None:
        await ctx.info(
            f"solve_equation: equation={equation!r} variable={variable!r} "
            f"domain={domain!r} numerical_near={numerical_near!r}"
        )

    eq = _parse_equation(equation)
    sym = parse_symbol(variable, context="variable")
    assumptions: list[str] = []

    # --- Numerical path ---
    if numerical_near is not None:
        near_expr = parse_expression(numerical_near, context="numerical_near")
        try:
            near_float = float(near_expr)
        except (TypeError, ValueError):
            raise ToolError(
                f"numerical_near '{numerical_near}' could not be converted to a float. "
                "Provide a numeric value like '1.5' or an expression like 'pi/2'."
            )
        try:
            num_sol = sp.nsolve(eq, sym, near_float)
        except Exception as e:
            raise ToolError(
                f"Numerical root-finding failed near {numerical_near}: {e}. "
                "Try a different starting value closer to the root."
            )
        assumptions.append(f"Numerical root found near {numerical_near}")
        sol_str = str(num_sol)
        sol_latex = sp.latex(num_sol)
        return format_result(
            num_sol,
            assumptions=assumptions,
            extra={
                "solutions": [sol_str],
                "solutions_latex": [sol_latex],
                "count": 1,
            },
        )

    # --- Symbolic path ---
    if domain == "real":
        domain_set = sp.S.Reals
        assumptions.append("solutions restricted to reals")
    elif domain == "positive":
        domain_set = sp.Interval.open(0, sp.oo)
        assumptions.append("solutions restricted to positive reals")
    elif domain == "complex":
        domain_set = sp.S.Complexes
    else:
        # Defensive guard: Pydantic's Literal type catches this on the normal
        # dispatch path, but a direct Python call (e.g. test harness) can
        # bypass validation.  Fail loudly rather than silently defaulting.
        raise ToolError(
            f"Unknown domain {domain!r}. Valid values: 'real', 'complex', 'positive'."
        )

    solution_set = sp.solveset(eq, sym, domain=domain_set)

    # --- Handle the different set types solveset can return ---

    if isinstance(solution_set, EmptySet):
        return format_result(
            solution_set,
            assumptions=assumptions,
            extra={"solutions": [], "solutions_latex": [], "count": 0},
        )

    if isinstance(solution_set, ConditionSet):
        raise ToolError(
            "SymPy couldn't find a closed form. "
            "Re-call with `numerical_near` set to an approximate value near the root you want."
        )

    if isinstance(solution_set, FiniteSet):
        sols = list(solution_set)
        return format_result(
            solution_set,
            assumptions=assumptions,
            extra={
                "solutions": [str(s) for s in sols],
                "solutions_latex": [sp.latex(s) for s in sols],
                "count": len(sols),
            },
        )

    # Infinite / ImageSet / Union — infinite solution family.
    # Attempt to extract a representative element for documentation.
    try:
        representative = next(iter(solution_set))
        rep_strs = [str(representative)]
        rep_latex = [sp.latex(representative)]
    except (StopIteration, TypeError, NotImplementedError):
        rep_strs = []
        rep_latex = []

    assumptions.append(
        f"Infinite solution family: {str(solution_set)}. "
        "Use numerical_near to find a specific root."
    )
    return format_result(
        solution_set,
        assumptions=assumptions,
        extra={
            "solutions": rep_strs,
            "solutions_latex": rep_latex,
            "count": -1,
        },
    )
