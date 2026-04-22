"""Tests for the evaluate_limit tool."""

import re

import pytest
import sympy as sp
from fastmcp.exceptions import ToolError
from unittest.mock import AsyncMock

from src.tools.evaluate_limit import evaluate_limit


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sin_x_over_x_at_zero():
    """sin(x)/x as x→0 two-sided should be exactly 1."""
    result = await evaluate_limit(
        expression="sin(x)/x",
        variable="x",
        point="0",
        direction="both",
        ctx=None,
    )
    assert result["result"] == "1"
    assert result["is_exact"] is True
    assert result["assumptions"] == []


@pytest.mark.asyncio
async def test_one_over_x_at_zero_left():
    """1/x as x→0 from the left should be -oo."""
    result = await evaluate_limit(
        expression="1/x",
        variable="x",
        point="0",
        direction="left",
        ctx=None,
    )
    assert result["result"] == "-oo"
    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_one_over_x_at_zero_right():
    """1/x as x→0 from the right should be +oo."""
    result = await evaluate_limit(
        expression="1/x",
        variable="x",
        point="0",
        direction="right",
        ctx=None,
    )
    assert result["result"] == "oo"
    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_one_over_x_at_zero_both_is_nan():
    """1/x as x→0 two-sided: one-sided limits disagree, result is nan."""
    result = await evaluate_limit(
        expression="1/x",
        variable="x",
        point="0",
        direction="both",
        ctx=None,
    )
    assert result["result"] == "nan"
    # The assumptions list must explain the disagreement.
    assert len(result["assumptions"]) == 1
    note = result["assumptions"][0]
    assert "-oo" in note
    assert "oo" in note
    assert "left" in note.lower() or "right" in note.lower()


@pytest.mark.asyncio
async def test_compound_interest_limit_at_infinity():
    """(1 + 1/x)^x as x→oo should be Euler's number E."""
    result = await evaluate_limit(
        expression="(1 + 1/x)**x",
        variable="x",
        point="oo",
        ctx=None,
    )
    assert result["result"] == "E"
    assert result["is_exact"] is True
    # Direction should be noted as ignored when going to infinity.
    assert any("direction ignored" in a for a in result["assumptions"])


@pytest.mark.asyncio
async def test_compound_interest_explicit_direction_at_infinity():
    """Explicit direction='left' with point='oo' should still work and note direction ignored."""
    result = await evaluate_limit(
        expression="(1 + 1/x)**x",
        variable="x",
        point="oo",
        direction="left",
        ctx=None,
    )
    assert result["result"] == "E"
    assert any("direction ignored" in a for a in result["assumptions"])


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_error_caret_exponent():
    """Using ^ for exponentiation should raise ToolError coaching the user to use **."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await evaluate_limit(
            expression="x^2",
            variable="x",
            point="0",
            ctx=None,
        )


@pytest.mark.asyncio
async def test_parse_error_bad_syntax():
    """Malformed expression (unclosed paren) should raise ToolError."""
    with pytest.raises(ToolError):
        await evaluate_limit(
            expression="sin(",
            variable="x",
            point="0",
            ctx=None,
        )


# ---------------------------------------------------------------------------
# Context logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctx_logging_called():
    """When ctx is provided, ctx.info should be called at least once."""
    ctx = AsyncMock()
    await evaluate_limit(
        expression="sin(x)/x",
        variable="x",
        point="0",
        ctx=ctx,
    )
    ctx.info.assert_called_once()
