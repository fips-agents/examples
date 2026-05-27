"""
End-to-end integration tests for MCP server startup and component discovery.

Tests that the server correctly discovers the calculus tools via
FileSystemProvider, and that discovered components behave correctly at runtime.
"""

import pytest
from fastmcp import Client
from fastmcp.utilities.tests import run_server_async

from src.core.server import create_server


@pytest.fixture
async def client():
    """Shared in-process client wrapping a freshly created server."""
    mcp = create_server()
    async with Client(mcp) as c:
        yield c


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = [
    "differentiate",
    "evaluate_limit",
    "evaluate_numeric",
    "integrate",
    "simplify_expression",
    "solve_equation",
    "solve_ode",
    "taylor_series",
]


@pytest.mark.parametrize("tool_name", EXPECTED_TOOLS)
async def test_server_discovers_tools(client, tool_name):
    """Server discovers all expected calculus tools via FileSystemProvider."""
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert tool_name in names, f"Expected tool '{tool_name}' not found in {sorted(names)}"


async def test_no_example_tools_present(client):
    """Example tools from the scaffold template have been removed."""
    tools = await client.list_tools()
    names = {t.name for t in tools}
    example_tools = {"echo", "delete_all", "get_weather", "write_release_notes"}
    found = names & example_tools
    assert not found, f"Example tools should have been removed: {sorted(found)}"


# ---------------------------------------------------------------------------
# Tool behaviour tests
# ---------------------------------------------------------------------------


async def test_differentiate_basic(client):
    """differentiate computes d/dx of x**2 correctly."""
    result = await client.call_tool(
        "differentiate",
        {"expression": "x**2", "variables": ["x"]},
    )
    assert not result.is_error, f"differentiate returned an error: {result}"
    assert result.data["result"] == "2*x"
    assert result.data["is_exact"] is True


async def test_simplify_expression_basic(client):
    """simplify_expression simplifies sin(x)**2 + cos(x)**2 to 1."""
    result = await client.call_tool(
        "simplify_expression",
        {"expression": "sin(x)**2 + cos(x)**2", "form": "simplify"},
    )
    assert not result.is_error, f"simplify_expression returned an error: {result}"
    assert result.data["result"] == "1"


async def test_integrate_indefinite(client):
    """integrate computes the indefinite integral of 2*x."""
    result = await client.call_tool(
        "integrate",
        {"expression": "2*x", "variable": "x"},
    )
    assert not result.is_error, f"integrate returned an error: {result}"
    assert result.data["result"] == "x**2"


async def test_evaluate_numeric_basic(client):
    """evaluate_numeric evaluates sqrt(2) to a numerical value."""
    result = await client.call_tool(
        "evaluate_numeric",
        {"expression": "sqrt(2)"},
    )
    assert not result.is_error, f"evaluate_numeric returned an error: {result}"
    # Should start with 1.41421...
    assert result.data["result"].startswith("1.4142")


# ---------------------------------------------------------------------------
# HTTP transport test
# ---------------------------------------------------------------------------


async def test_http_transport_lists_tools():
    """Server starts on HTTP transport and responds to tool listing."""
    mcp = create_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with Client(url) as http_client:
            tools = await http_client.list_tools()
            names = {t.name for t in tools}
            assert "differentiate" in names, (
                f"differentiate not found via HTTP transport: {sorted(names)}"
            )
            assert len(tools) >= len(EXPECTED_TOOLS), (
                f"HTTP transport discovered only {len(tools)} tools, "
                f"expected at least {len(EXPECTED_TOOLS)}"
            )
