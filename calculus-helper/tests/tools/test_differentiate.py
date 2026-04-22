"""Tests for the differentiate tool."""

import re

import pytest
import sympy as sp
from fastmcp.exceptions import ToolError
from unittest.mock import AsyncMock

from src.calc import parse_expression
from src.tools.differentiate import differentiate


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slope_at_point():
    """d/dx(x³ - 2x) evaluated at x=1 should equal 1."""
    ctx = AsyncMock()
    result = await differentiate(
        expression="x**3 - 2*x",
        variables=["x"],
        at_point={"x": "1"},
        ctx=ctx,
    )

    assert result["result"] == "1", f"Expected '1', got {result['result']!r}"
    assert result["is_exact"] is True
    ctx.info.assert_called_once()


@pytest.mark.asyncio
async def test_second_order_derivative():
    """d²/dx²(sin(x)) should equal -sin(x)."""
    ctx = AsyncMock()
    result = await differentiate(
        expression="sin(x)",
        variables=["x", "x"],
        ctx=ctx,
    )

    x = sp.Symbol("x")
    parsed = parse_expression(result["result"])
    assert sp.simplify(parsed - (-sp.sin(x))) == 0, (
        f"Expected -sin(x), got {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_mixed_partial_derivative():
    """∂²/∂x∂y(x²y³) should equal 6*x*y²."""
    ctx = AsyncMock()
    result = await differentiate(
        expression="x**2 * y**3",
        variables=["x", "y"],
        ctx=ctx,
    )

    x, y = sp.Symbol("x"), sp.Symbol("y")
    parsed = parse_expression(result["result"])
    assert sp.simplify(parsed - 6 * x * y**2) == 0, (
        f"Expected 6*x*y**2, got {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_ctx_none_allowed():
    """Tool must work when ctx=None (test-harness usage)."""
    result = await differentiate(
        expression="x**2",
        variables=["x"],
        ctx=None,
    )
    assert result["result"] == "2*x"


@pytest.mark.asyncio
async def test_variable_absent_adds_assumption():
    """Differentiating w.r.t. a variable not in the expression warns but still returns 0."""
    result = await differentiate(
        expression="x**2",
        variables=["z"],
        ctx=None,
    )
    assert result["result"] == "0"
    assert any("'z' not present" in note for note in result["assumptions"])


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_variables_raises():
    """Passing variables=[] must raise a descriptive ToolError."""
    with pytest.raises(ToolError, match="at least one variable"):
        await differentiate(
            expression="x**2",
            variables=[],
            ctx=None,
        )


@pytest.mark.asyncio
async def test_caret_in_expression_raises():
    """Using '^' instead of '**' must raise a ToolError coaching the fix."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await differentiate(
            expression="x^2",
            variables=["x"],
            ctx=None,
        )


@pytest.mark.asyncio
async def test_at_point_absent_variable_adds_assumption():
    """Substituting a variable not in the expression warns but does not fail."""
    result = await differentiate(
        expression="x**2",
        variables=["x"],
        at_point={"z": "5"},
        ctx=None,
    )
    # Derivative is 2*x; substituting z has no effect — result should still be 2*x.
    assert "2*x" in result["result"]
    assert any("'z' not present" in note for note in result["assumptions"])
