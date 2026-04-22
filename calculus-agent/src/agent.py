"""Calculus Helper — uses MCP-connected math tools to solve calculus problems."""

from __future__ import annotations

from fipsagents.baseagent import BaseAgent, StepResult


class CalculusHelper(BaseAgent):
    """An agent that solves calculus problems using MCP tools."""

    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(response.content)


if __name__ == "__main__":
    from fipsagents.baseagent import load_config
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=CalculusHelper,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )
    server.run(host=config.server.host, port=config.server.port)
