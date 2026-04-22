"""Tests for the solve_ode tool."""

import pytest
import sympy as sp
from fastmcp.exceptions import ToolError
from unittest.mock import AsyncMock

from src.tools.solve_ode import solve_ode


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_order_exponential():
    """f'(x) - f(x) = 0 → general solution C1*exp(x)."""
    ctx = AsyncMock()
    result = await solve_ode(
        equation="f'(x) - f(x) = 0",
        function="f",
        variable="x",
        ctx=ctx,
    )

    assert "exp(x)" in result["result"], (
        f"Expected 'exp(x)' in result: {result['result']!r}"
    )
    assert "C1" in result["result"], (
        f"Expected integration constant 'C1' in result: {result['result']!r}"
    )
    ctx.info.assert_called_once()


@pytest.mark.asyncio
async def test_sho_general_solution():
    """f''(x) + f(x) = 0 → general solution C1*sin(x) + C2*cos(x)."""
    result = await solve_ode(
        equation="f''(x) + f(x) = 0",
        function="f",
        variable="x",
        ctx=None,
    )

    res = result["result"]
    assert "sin" in res or "cos" in res, (
        f"Expected sin/cos in SHO result: {res!r}"
    )
    assert "C1" in res, f"Expected C1 in SHO result: {res!r}"
    assert "C2" in res, f"Expected C2 in SHO result: {res!r}"


@pytest.mark.asyncio
async def test_sho_with_initial_conditions():
    """SHO with f(0)=1, f'(0)=0 → particular solution f(x) = cos(x)."""
    result = await solve_ode(
        equation="f''(x) + f(x) = 0",
        function="f",
        variable="x",
        initial_conditions={"f(0)": "1", "f'(0)": "0"},
        ctx=None,
    )

    # Parse the result and check symbolic equality.
    x = sp.Symbol("x")
    f = sp.Function("f")
    expected = sp.Eq(f(x), sp.cos(x))

    result_expr = sp.sympify(result["result"])
    # Both should be Eq(f(x), cos(x)); check via simplification of both sides.
    diff = sp.simplify(result_expr.rhs - expected.rhs)
    assert diff == 0, (
        f"Expected f(x) = cos(x), but result RHS differs by {diff!r}. "
        f"Full result: {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_derivative_notation_accepted():
    """Explicit Derivative(...) notation also works."""
    result = await solve_ode(
        equation="Derivative(f(x), x) - f(x) = 0",
        function="f",
        variable="x",
        ctx=None,
    )
    assert "exp(x)" in result["result"], (
        f"Expected 'exp(x)' in result: {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_classification_in_assumptions():
    """Assumptions should contain an ODE classification string."""
    result = await solve_ode(
        equation="f''(x) + f(x) = 0",
        function="f",
        variable="x",
        ctx=None,
    )
    all_assumptions = " ".join(result["assumptions"])
    assert "classified as:" in all_assumptions, (
        f"Expected ODE classification in assumptions: {result['assumptions']}"
    )


@pytest.mark.asyncio
async def test_ctx_none_allowed():
    """Tool must work when ctx=None (test-harness usage)."""
    result = await solve_ode(
        equation="f'(x) = 0",
        function="f",
        variable="x",
        ctx=None,
    )
    assert result is not None


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_solvable_ode_raises_tool_error():
    """A nonlinear ODE SymPy can't solve raises ToolError with helpful message."""
    # f'(x) = f(x)**2 + f(x) + x**3 + sin(x) triggers NotImplementedError in dsolve.
    with pytest.raises(ToolError, match=r"(?i)solvable classes"):
        await solve_ode(
            equation="f'(x) - f(x)**2 - f(x) - x**3 - sin(x) = 0",
            function="f",
            variable="x",
            ctx=None,
        )


@pytest.mark.asyncio
async def test_parse_error_raises_tool_error():
    """A syntactically invalid equation raises ToolError, not a bare exception."""
    with pytest.raises(ToolError):
        await solve_ode(
            equation="f'(x) + = 0",
            function="f",
            variable="x",
            ctx=None,
        )


@pytest.mark.asyncio
async def test_caret_in_equation_raises():
    """Using '^' in the ODE raises ToolError with coaching."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await solve_ode(
            equation="f'(x) + x^2 = 0",
            function="f",
            variable="x",
            ctx=None,
        )


@pytest.mark.asyncio
async def test_ic_function_name_mismatch_raises():
    """Regression: an IC key that names a different function than the one being
    solved for (e.g. 'g(0)' when solving for 'f') must raise ToolError.

    Previously the IC key's function name was silently ignored, so an agent
    typo like ``{"g(0)": "1"}`` would be treated as ``{"f(0)": "1"}`` -- a
    silent correctness bug."""
    with pytest.raises(ToolError, match=r"(?i)function.*'g'.*'f'|'f'.*'g'"):
        await solve_ode(
            equation="f'(x) + f(x) = 0",
            function="f",
            variable="x",
            initial_conditions={"g(0)": "1"},
            ctx=None,
        )
