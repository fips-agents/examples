"""Calculus Coordinator — tutor agent that delegates math to a specialist."""

from __future__ import annotations

from fipsagents.baseagent import BaseAgent, StepResult


class CalculusCoordinator(BaseAgent):
    """A tutor agent that delegates calculus computation to a specialist subagent."""

    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(response.content)


if __name__ == "__main__":
    from fipsagents.baseagent import load_config
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=CalculusCoordinator,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )
    server.run(host=config.server.host, port=config.server.port)
