"""Tests for evaluate_numeric tool."""

import pytest
from fastmcp.exceptions import ToolError
from unittest.mock import AsyncMock

from src.tools.evaluate_numeric import evaluate_numeric


@pytest.mark.asyncio
async def test_sqrt2_no_subs():
    """sqrt(2) with no substitutions should give ~1.41421356... and exact_form=sqrt(2)."""
    ctx = AsyncMock()
    result = await evaluate_numeric(expression="sqrt(2)", ctx=ctx)

    assert result["result"].startswith("1.41421356"), (
        f"Expected result to start with '1.41421356', got {result['result']!r}"
    )
    assert result["exact_form"] == "sqrt(2)", (
        f"Expected exact_form 'sqrt(2)', got {result['exact_form']!r}"
    )
    assert result["is_exact"] is False  # sp.N produces a Float
    assert "latex" in result
    ctx.info.assert_called_once()


@pytest.mark.asyncio
async def test_substitution_with_pi():
    """x**2 + 1 with x=pi should give ~10.8696... and exact_form containing pi."""
    ctx = AsyncMock()
    result = await evaluate_numeric(
        expression="x**2 + 1",
        substitutions={"x": "pi"},
        ctx=ctx,
    )

    numeric_val = float(result["result"])
    assert abs(numeric_val - 10.8696044010894) < 1e-6, (
        f"Expected ~10.8696, got {result['result']!r}"
    )
    # exact_form should be the substituted-but-unevaluated expression
    assert "pi" in result["exact_form"], (
        f"Expected 'pi' in exact_form, got {result['exact_form']!r}"
    )


@pytest.mark.asyncio
async def test_free_variable_after_subs_raises():
    """x + y with only x substituted should raise ToolError mentioning 'y'."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match=r"\by\b"):
        await evaluate_numeric(
            expression="x + y",
            substitutions={"x": "1"},
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_precision_over_max_raises():
    """precision=51 should raise ToolError mentioning 'precision'."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match=r"(?i)precision"):
        await evaluate_numeric(
            expression="sqrt(2)",
            precision=51,
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_no_substitutions_no_assumptions():
    """When no substitutions are given, assumptions list should be empty."""
    ctx = AsyncMock()
    result = await evaluate_numeric(expression="pi", ctx=ctx)
    assert result["assumptions"] == [], (
        f"Expected empty assumptions for no-subs case, got {result['assumptions']!r}"
    )


@pytest.mark.asyncio
async def test_substitution_adds_assumption():
    """When substitutions are provided, assumptions should note it."""
    ctx = AsyncMock()
    result = await evaluate_numeric(
        expression="x**2",
        substitutions={"x": "3"},
        ctx=ctx,
    )
    assert any("substitut" in a.lower() for a in result["assumptions"]), (
        f"Expected substitution note in assumptions, got {result['assumptions']!r}"
    )


@pytest.mark.asyncio
async def test_ctx_none_does_not_raise():
    """Tool should work correctly when ctx=None."""
    result = await evaluate_numeric(expression="sqrt(2)", ctx=None)
    assert result["result"].startswith("1.41421356")


@pytest.mark.asyncio
async def test_custom_precision():
    """precision=5 should give a 5-significant-digit result for sqrt(2)."""
    ctx = AsyncMock()
    result = await evaluate_numeric(expression="sqrt(2)", precision=5, ctx=ctx)
    # sp.N(sqrt(2), 5) = 1.4142
    assert result["result"].startswith("1.4142"), (
        f"Expected 5-digit approximation starting with '1.4142', got {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_log10_not_mangled_by_parser():
    """Regression: SymPy's `split_symbols` transformer silently shreds 'log10'
    into 'l*o*g*10'.  Our parser must NOT do that -- log10(100) must be 2."""
    ctx = AsyncMock()
    result = await evaluate_numeric(expression="log10(100)", ctx=ctx)
    assert float(result["result"]) == pytest.approx(2.0), (
        f"log10(100) should be 2.0, got {result['result']!r} — "
        "parser may be splitting multi-letter identifiers into single symbols."
    )


@pytest.mark.asyncio
async def test_log2_not_mangled_by_parser():
    """Regression: log2(8) must parse to a real log-base-2 call, not l*o*g*2*(8)."""
    ctx = AsyncMock()
    result = await evaluate_numeric(expression="log2(8)", ctx=ctx)
    assert float(result["result"]) == pytest.approx(3.0), (
        f"log2(8) should be 3.0, got {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_arcsin_alias_parses():
    """Regression: 'arcsin' (as opposed to 'asin') must resolve to sp.asin,
    not get split into 'a*r*c*s*i*n'."""
    ctx = AsyncMock()
    # arcsin(1) == pi/2, numerically 1.5707963...
    result = await evaluate_numeric(expression="arcsin(1)", ctx=ctx)
    assert float(result["result"]) == pytest.approx(1.5707963267948966), (
        f"arcsin(1) should be pi/2 ≈ 1.5708, got {result['result']!r}"
    )


@pytest.mark.asyncio
async def test_unused_substitution_noted_in_assumptions():
    """When a substitution key doesn't match any symbol in the expression
    (e.g. agent typo), report it in assumptions so the agent can catch the bug."""
    ctx = AsyncMock()
    result = await evaluate_numeric(
        expression="x**2", substitutions={"x": "2", "z": "99"}, ctx=ctx
    )
    unused_noted = any(
        "'z'" in a and "no effect" in a.lower() for a in result["assumptions"]
    )
    assert unused_noted, (
        f"Expected 'z had no effect' note in assumptions, got {result['assumptions']!r}"
    )
