"""Tests for the solve_equation tool."""

import pytest
import sympy as sp
from fastmcp.exceptions import ToolError
from unittest.mock import AsyncMock

from src.tools.solve_equation import solve_equation


# ---------------------------------------------------------------------------
# Happy paths — equation form
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quadratic_equation_form_complex():
    """'x**2 - 4 = 0' (explicit equation) in complex domain yields {-2, 2}."""
    ctx = AsyncMock()
    result = await solve_equation(
        equation="x**2 - 4 = 0",
        variable="x",
        domain="complex",
        ctx=ctx,
    )

    assert result["count"] == 2, f"Expected count=2, got {result['count']}"
    assert "-2" in result["solutions"], f"Expected '-2' in solutions: {result['solutions']}"
    assert "2" in result["solutions"], f"Expected '2' in solutions: {result['solutions']}"
    assert result["is_exact"] is True
    ctx.info.assert_called_once()


@pytest.mark.asyncio
async def test_quadratic_expression_form_complex():
    """'x**2 - 4' (expression = 0) in complex domain yields same result."""
    result = await solve_equation(
        equation="x**2 - 4",
        variable="x",
        domain="complex",
        ctx=None,
    )

    assert result["count"] == 2
    assert set(result["solutions"]) == {"-2", "2"}, (
        f"Expected {{'-2', '2'}}, got {set(result['solutions'])}"
    )
    assert result["is_exact"] is True


# ---------------------------------------------------------------------------
# Domain filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_positive_domain_filters_negative_root():
    """domain='positive' for x**2 - 4 returns only x=2."""
    result = await solve_equation(
        equation="x**2 - 4",
        variable="x",
        domain="positive",
        ctx=None,
    )

    assert result["count"] == 1, f"Expected count=1, got {result['count']}"
    assert result["solutions"] == ["2"], (
        f"Expected ['2'], got {result['solutions']}"
    )
    assert any("positive" in a for a in result["assumptions"]), (
        f"Expected 'positive' in assumptions: {result['assumptions']}"
    )


@pytest.mark.asyncio
async def test_real_domain_no_solutions():
    """x**2 + 1 = 0 has no real solutions; expect empty list and count=0."""
    result = await solve_equation(
        equation="x**2 + 1 = 0",
        variable="x",
        domain="real",
        ctx=None,
    )

    assert result["solutions"] == [], f"Expected [], got {result['solutions']}"
    assert result["count"] == 0, f"Expected count=0, got {result['count']}"
    assert any("real" in a for a in result["assumptions"])


# ---------------------------------------------------------------------------
# Infinite solutions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_infinite_solutions_sin():
    """sin(x) = 0 has infinitely many real solutions; expect count=-1."""
    result = await solve_equation(
        equation="sin(x) = 0",
        variable="x",
        domain="real",
        ctx=None,
    )

    assert result["count"] == -1, (
        f"Expected count=-1 for infinite solutions, got {result['count']}"
    )
    # Assumptions should describe the infinite family.
    all_assumptions = " ".join(result["assumptions"]).lower()
    assert "infinite" in all_assumptions or "imageset" in all_assumptions.lower() or "union" in all_assumptions.lower(), (
        f"Expected infinite-family note in assumptions: {result['assumptions']}"
    )


# ---------------------------------------------------------------------------
# Numerical path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_numerical_near_transcendental():
    """cos(x) - x = 0 solved numerically near x=1 yields ~0.7391."""
    result = await solve_equation(
        equation="cos(x) - x = 0",
        variable="x",
        numerical_near="1",
        ctx=None,
    )

    assert result["count"] == 1, f"Expected count=1, got {result['count']}"
    assert len(result["solutions"]) == 1

    sol_val = float(sp.sympify(result["solutions"][0]))
    assert abs(sol_val - 0.739085) < 1e-4, (
        f"Expected ~0.7391, got {sol_val}"
    )
    assert result["is_exact"] is False
    assert any("numerical" in a.lower() for a in result["assumptions"]), (
        f"Expected numerical assumption, got: {result['assumptions']}"
    )


# ---------------------------------------------------------------------------
# ConditionSet (symbolic solve fails, no numerical_near)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_set_raises_tool_error():
    """When solveset returns a ConditionSet, raise ToolError with coaching message."""
    # x*exp(x) - 1 = 0 returns a ConditionSet in the real domain.
    with pytest.raises(ToolError, match="numerical_near"):
        await solve_equation(
            equation="x*exp(x) - 1 = 0",
            variable="x",
            domain="real",
            ctx=None,
        )


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_equals_raises():
    """'x = 1 = 2' has two single '=' signs; must raise ToolError."""
    with pytest.raises(ToolError, match="="):
        await solve_equation(
            equation="x = 1 = 2",
            variable="x",
            ctx=None,
        )


@pytest.mark.asyncio
async def test_caret_in_equation_raises():
    """Using '^' for exponent raises ToolError with coaching."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await solve_equation(
            equation="x^2 - 4 = 0",
            variable="x",
            ctx=None,
        )


@pytest.mark.asyncio
async def test_latex_forms_present():
    """Result includes solutions_latex with valid LaTeX strings."""
    result = await solve_equation(
        equation="x**2 - 4 = 0",
        variable="x",
        domain="complex",
        ctx=None,
    )

    assert len(result["solutions_latex"]) == 2
    # LaTeX for -2 and 2 should be "-2" and "2" respectively.
    for s in result["solutions_latex"]:
        assert isinstance(s, str) and len(s) > 0


@pytest.mark.asyncio
async def test_ctx_none_allowed():
    """Tool must work when ctx=None (test-harness usage)."""
    result = await solve_equation(
        equation="x - 5",
        variable="x",
        ctx=None,
    )
    assert "5" in result["solutions"]
