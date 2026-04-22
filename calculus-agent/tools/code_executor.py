import os
import httpx
from fipsagents.baseagent.tools import tool

SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://localhost:8000")


@tool(
    description=(
        "Execute Python code in a secure sandbox. Use this for numerical "
        "computation, data analysis, building tables, or any task that "
        "benefits from running code. Returns stdout and the expression result."
    ),
    visibility="llm_only",
)
async def code_executor(code: str) -> str:
    """Execute Python code and return the output.

    Args:
        code: Python source code to execute. The sandbox has access to
              math, statistics, numpy, and other data-science libraries
              depending on the active profile.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{SANDBOX_URL}/execute",
            json={"code": code},
        )

    if response.status_code != 200:
        return f"Sandbox error (HTTP {response.status_code}): {response.text}"

    result = response.json()
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("result") is not None:
        parts.append(f"Result: {result['result']}")
    if result.get("stderr"):
        parts.append(f"Stderr: {result['stderr']}")
    if result.get("error"):
        parts.append(f"Error: {result['error']}")

    return "\n".join(parts) if parts else "(no output)"
