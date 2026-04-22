"""Tests for simplify_expression tool."""

import pytest
from fastmcp.exceptions import ToolError
from unittest.mock import AsyncMock

from src.tools.simplify_expression import simplify_expression


@pytest.mark.asyncio
async def test_trig_identity_simplifies_to_one():
    """sin(x)**2 + cos(x)**2 should simplify to 1 (exact)."""
    ctx = AsyncMock()
    result = await simplify_expression(
        expression="sin(x)**2 + cos(x)**2",
        form="simplify",
        ctx=ctx,
    )
    assert result["result"] == "1", f"Expected '1', got {result['result']!r}"
    assert result["is_exact"] is True
    assert "latex" in result
    ctx.info.assert_called_once()


@pytest.mark.asyncio
async def test_expand_cubic():
    """(x+1)**3 expanded should contain x**3 and 3*x**2."""
    ctx = AsyncMock()
    result = await simplify_expression(
        expression="(x+1)**3",
        form="expand",
        ctx=ctx,
    )
    assert "x**3" in result["result"], f"Missing x**3 in {result['result']!r}"
    assert "3*x**2" in result["result"], f"Missing 3*x**2 in {result['result']!r}"
    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_factor_difference_of_squares():
    """x**2 - 1 factored should contain (x - 1) and (x + 1)."""
    ctx = AsyncMock()
    result = await simplify_expression(
        expression="x**2 - 1",
        form="factor",
        ctx=ctx,
    )
    assert "(x - 1)" in result["result"], f"Missing (x - 1) in {result['result']!r}"
    assert "(x + 1)" in result["result"], f"Missing (x + 1) in {result['result']!r}"
    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_collect_requires_variable():
    """form='collect' without variable raises ToolError mentioning 'variable'."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match=r"(?i)variable"):
        await simplify_expression(
            expression="x**2 + x*y + x",
            form="collect",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_invalid_expression_caret_gives_coaching():
    """Using ^ instead of ** raises ToolError with ** coaching message."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match=r"\*\*"):
        await simplify_expression(
            expression="x^2",
            form="simplify",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_collect_with_variable():
    """form='collect' with a variable should group polynomial by that variable."""
    ctx = AsyncMock()
    result = await simplify_expression(
        expression="x**2 + 2*x + x*y",
        form="collect",
        variable="x",
        ctx=ctx,
    )
    # Result should have x factored; check it round-trips without error
    assert "x" in result["result"]
    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_ctx_none_does_not_raise():
    """Tool should work correctly when ctx=None (test harness, no logging)."""
    result = await simplify_expression(
        expression="sin(x)**2 + cos(x)**2",
        form="simplify",
        ctx=None,
    )
    assert result["result"] == "1"
