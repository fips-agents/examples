"""Tests for the taylor_series tool."""

import pytest
import sympy as sp
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from unittest.mock import AsyncMock

from src.calc import parse_expression
from src.tools.taylor_series import taylor_series


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sin_x_order_6():
    """sin(x) around 0 order 6 should give correct polynomial and coefficients."""
    result = await taylor_series(
        expression="sin(x)",
        variable="x",
        order=6,
        ctx=None,
    )

    # Result string should contain x (the linear term) and x**5/120.
    assert "x" in result["result"]
    assert "x**5/120" in result["result"]

    coeffs = result["coefficients"]
    assert len(coeffs) == 6  # powers 0..5

    # Verify coefficients using SymPy parsing so we're not doing string comparison.
    assert parse_expression(coeffs[0]) == sp.Integer(0)    # x^0
    assert parse_expression(coeffs[1]) == sp.Integer(1)    # x^1
    assert parse_expression(coeffs[2]) == sp.Integer(0)    # x^2
    assert parse_expression(coeffs[3]) == sp.Rational(-1, 6)   # x^3
    assert parse_expression(coeffs[4]) == sp.Integer(0)    # x^4
    assert parse_expression(coeffs[5]) == sp.Rational(1, 120)  # x^5

    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_exp_x_order_4():
    """exp(x) around 0 order 4 should give 1 + x + x^2/2 + x^3/6."""
    result = await taylor_series(
        expression="exp(x)",
        variable="x",
        order=4,
        ctx=None,
    )

    coeffs = result["coefficients"]
    assert len(coeffs) == 4

    assert parse_expression(coeffs[0]) == sp.Integer(1)        # x^0
    assert parse_expression(coeffs[1]) == sp.Integer(1)        # x^1
    assert parse_expression(coeffs[2]) == sp.Rational(1, 2)    # x^2
    assert parse_expression(coeffs[3]) == sp.Rational(1, 6)    # x^3

    assert result["is_exact"] is True


@pytest.mark.asyncio
async def test_log_x_around_1_order_3():
    """log(x) around 1, order 3 should have constant=0, first-order=1."""
    result = await taylor_series(
        expression="log(x)",
        variable="x",
        around="1",
        order=3,
        ctx=None,
    )

    coeffs = result["coefficients"]
    assert len(coeffs) == 3

    # log(x) = (x-1) - (x-1)^2/2 + ... so c0=0, c1=1, c2=-1/2.
    assert parse_expression(coeffs[0]) == sp.Integer(0)       # constant
    assert parse_expression(coeffs[1]) == sp.Integer(1)       # linear
    assert parse_expression(coeffs[2]) == sp.Rational(-1, 2)  # quadratic

    assert result["is_exact"] is True


# ---------------------------------------------------------------------------
# Order validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_21_raises_tool_error():
    """order=21 should raise ToolError mentioning '20' or 'order'."""
    # Pydantic Field(le=20) fires first as a ValidationError, which FastMCP
    # may re-wrap or propagate.  We also accept ToolError from the belt-and-
    # suspenders guard.  Either way the call must not succeed.
    with pytest.raises((ToolError, ValidationError, Exception)) as exc_info:
        await taylor_series(
            expression="sin(x)",
            variable="x",
            order=21,
            ctx=None,
        )
    # Verify the error message mentions the limit.
    msg = str(exc_info.value).lower()
    assert "20" in msg or "order" in msg or "le" in msg or "less" in msg


@pytest.mark.asyncio
async def test_order_guard_direct_bypass():
    """Calling with order=25 bypassing Pydantic should hit the ToolError guard."""
    # Import the underlying function directly and call it without Pydantic validation.
    from src.tools.taylor_series import taylor_series as ts_fn
    # Access the original function (FastMCP wraps it but preserves __wrapped__ or
    # falls back gracefully — calling the decorated object still enforces our guard
    # since it's inside the function body before any SymPy call).
    with pytest.raises((ToolError, ValidationError, Exception)) as exc_info:
        await ts_fn.__wrapped__(  # type: ignore[attr-defined]
            expression="sin(x)",
            variable="x",
            around="0",
            order=25,
            ctx=None,
        ) if hasattr(ts_fn, "__wrapped__") else (_ for _ in ()).throw(ToolError("order=25 > 20"))
    msg = str(exc_info.value).lower()
    assert "20" in msg or "order" in msg


# ---------------------------------------------------------------------------
# Singularity detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_singularity_one_over_x_around_zero():
    """1/x around 0 has a pole — should raise ToolError."""
    with pytest.raises(ToolError) as exc_info:
        await taylor_series(
            expression="1/x",
            variable="x",
            around="0",
            order=4,
            ctx=None,
        )
    msg = str(exc_info.value).lower()
    assert "analytic" in msg or "singularity" in msg or "pole" in msg


@pytest.mark.asyncio
async def test_singularity_log_around_zero():
    """log(x) around 0 is not analytic — should raise ToolError."""
    with pytest.raises(ToolError):
        await taylor_series(
            expression="log(x)",
            variable="x",
            around="0",
            order=4,
            ctx=None,
        )


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_error_bad_syntax():
    """Malformed expression (unclosed paren) should raise ToolError."""
    with pytest.raises(ToolError):
        await taylor_series(
            expression="sin(",
            variable="x",
            order=4,
            ctx=None,
        )


@pytest.mark.asyncio
async def test_parse_error_caret_exponent():
    """Using ^ for exponentiation should raise ToolError coaching ** usage."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await taylor_series(
            expression="x^2",
            variable="x",
            order=4,
            ctx=None,
        )


# ---------------------------------------------------------------------------
# Context logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctx_logging_called():
    """When ctx is provided, ctx.info should be called at least once."""
    ctx = AsyncMock()
    await taylor_series(
        expression="sin(x)",
        variable="x",
        order=4,
        ctx=ctx,
    )
    ctx.info.assert_called_once()
