"""End-to-end integration tests for the calculus-helper MCP server.

Exercises the actual FastMCP server process (in-process and over HTTP) to
verify tool discovery and round-trip invocation work through the real client
API -- not just direct Python calls to the tool functions.
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.utilities.tests import run_server_async

from src.core.server import create_server


@pytest.fixture
async def client():
    """Shared in-process client wrapping a freshly created server."""
    mcp = create_server()
    async with Client(mcp) as c:
        yield c


# The 8 calculus tools this server exposes.
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


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", EXPECTED_TOOLS)
async def test_server_discovers_tools(client, tool_name):
    """Server discovers all expected calculus tools via FileSystemProvider."""
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert tool_name in names, (
        f"Expected tool '{tool_name}' not found in {sorted(names)}"
    )


async def test_exactly_eight_tools_registered(client):
    """No unexpected tools leak in (regression guard against example rot)."""
    tools = await client.list_tools()
    names = sorted(t.name for t in tools)
    assert names == sorted(EXPECTED_TOOLS), (
        f"Unexpected tool set. Got: {names}. Expected: {sorted(EXPECTED_TOOLS)}"
    )


# ---------------------------------------------------------------------------
# Round-trip through the MCP client API
# ---------------------------------------------------------------------------


async def test_differentiate_roundtrip(client):
    """differentiate via the real FastMCP client returns the expected dict."""
    result = await client.call_tool(
        "differentiate", {"expression": "x**3 - 2*x", "variables": ["x"]}
    )
    assert not result.is_error, f"differentiate returned an error: {result}"
    data = result.data
    assert data["result"] == "3*x**2 - 2", f"Unexpected result: {data}"
    assert data["is_exact"] is True


async def test_integrate_definite_roundtrip(client):
    """integrate definite integral via the MCP client API."""
    result = await client.call_tool(
        "integrate",
        {"expression": "x", "variable": "x", "lower_bound": "0", "upper_bound": "1"},
    )
    assert not result.is_error
    assert result.data["result"] == "1/2"
    assert result.data["is_exact"] is True


async def test_parse_error_surfaces_as_tool_error(client):
    """The '^' coaching error must propagate through the client as a ToolError."""
    with pytest.raises(ToolError, match=r"\*\*"):
        await client.call_tool(
            "differentiate", {"expression": "x^2", "variables": ["x"]}
        )


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


async def test_http_transport_lists_tools():
    """Server starts on HTTP transport and responds to tool listing."""
    mcp = create_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with Client(url) as http_client:
            tools = await http_client.list_tools()
            names = {t.name for t in tools}
            assert names == set(EXPECTED_TOOLS), (
                f"HTTP transport tool set mismatch. Got: {sorted(names)}"
            )
