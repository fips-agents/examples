"""Tests for the CalculusHelper example agent (tools, prompts, skills, rules).

This file tests the calculus-agent customizations on top of the generic
framework test suite (test_agent.py, test_tools.py, test_config.py, etc.).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fipsagents.baseagent.agent import BaseAgent, StepOutcome
from fipsagents.baseagent.config import AgentConfig, LLMConfig, LoopConfig, BackoffConfig
from fipsagents.baseagent.llm import LLMClient, ModelResponse
from fipsagents.baseagent.prompts import PromptLoader
from fipsagents.baseagent.skills import SkillLoader
from fipsagents.baseagent.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _TEMPLATE_ROOT / "tools"
_PROMPTS_DIR = _TEMPLATE_ROOT / "prompts"
_SKILLS_DIR = _TEMPLATE_ROOT / "skills"
_RULES_DIR = _TEMPLATE_ROOT / "rules"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {
        "model": LLMConfig(
            endpoint="http://test:8321/v1",
            name="test-model",
            temperature=0.5,
            max_tokens=256,
        ),
        "loop": LoopConfig(
            max_iterations=5,
            backoff=BackoffConfig(initial=0.01, max=0.05, multiplier=2.0),
        ),
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _mock_response(
    content: str | None = None,
    tool_calls: list[Any] | None = None,
) -> MagicMock:
    """Build a fake OpenAI ChatCompletion matching ModelResponse expectations."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


# ---------------------------------------------------------------------------
# Import the example agent
# ---------------------------------------------------------------------------

from agent import CalculusHelper  # noqa: E402


# ---------------------------------------------------------------------------
# Test: Agent instantiation
# ---------------------------------------------------------------------------


class TestCalculusHelperInstantiation:
    def test_is_base_agent_subclass(self):
        assert issubclass(CalculusHelper, BaseAgent)

    def test_can_instantiate_with_config(self):
        agent = CalculusHelper(config=_make_config())
        assert agent.config is None  # not yet set up
        assert isinstance(agent, BaseAgent)


# ---------------------------------------------------------------------------
# Test: step() method with mocked LLM
# ---------------------------------------------------------------------------


class TestCalculusHelperStep:
    """Test the step() method with mocked LLM responses."""

    async def _setup_agent(self) -> CalculusHelper:
        """Create and setup a CalculusHelper with real tools/prompts."""
        config = _make_config()
        agent = CalculusHelper(
            config=config,
            base_dir=_TEMPLATE_ROOT,
        )
        agent.config = config
        agent.llm = MagicMock(spec=LLMClient)
        agent.tools.discover(_TOOLS_DIR)

        if _PROMPTS_DIR.is_dir():
            agent.prompts.load_all(_PROMPTS_DIR)
        if _RULES_DIR.is_dir():
            agent.rules.load_all(_RULES_DIR)
        if _SKILLS_DIR.is_dir():
            agent.skills.load_all(_SKILLS_DIR)

        agent._setup_done = True
        return agent

    async def test_step_no_tool_calls(self):
        """step() completes when the LLM responds without tool calls."""
        agent = await self._setup_agent()
        agent.add_message("user", "What is the integral of x^2?")

        response = ModelResponse(
            _mock_response(content="The integral of x^2 is x^3/3 + C.")
        )
        agent.llm.call_model = AsyncMock(return_value=response)

        result = await agent.step()

        assert result.outcome is StepOutcome.DONE
        assert "x^3/3" in result.result or "x\u00b3/3" in result.result

    async def test_step_returns_content_string(self):
        """step() returns a plain string result, not a structured model."""
        agent = await self._setup_agent()
        agent.add_message("user", "Differentiate sin(x).")

        response = ModelResponse(
            _mock_response(content="The derivative of sin(x) is cos(x).")
        )
        agent.llm.call_model = AsyncMock(return_value=response)

        result = await agent.step()

        assert result.outcome is StepOutcome.DONE
        assert isinstance(result.result, str)


# ---------------------------------------------------------------------------
# Test: code_executor tool
# ---------------------------------------------------------------------------


class TestCodeExecutorTool:
    """Test the code_executor tool independently."""

    def test_tool_discovered_in_registry(self):
        registry = ToolRegistry()
        discovered = registry.discover(_TOOLS_DIR)
        names = [t.name for t in discovered]
        assert "code_executor" in names

    def test_code_executor_visibility(self):
        registry = ToolRegistry()
        registry.discover(_TOOLS_DIR)
        meta = registry.get("code_executor")
        assert meta is not None
        assert meta.visibility == "llm_only"

    def test_code_executor_in_llm_tools(self):
        registry = ToolRegistry()
        registry.discover(_TOOLS_DIR)
        llm_tools = registry.get_llm_tools()
        names = [t.name for t in llm_tools]
        assert "code_executor" in names

    def test_code_executor_not_in_agent_tools(self):
        """code_executor is llm_only, so it should not appear in agent tools."""
        registry = ToolRegistry()
        registry.discover(_TOOLS_DIR)
        agent_tools = registry.get_agent_tools()
        names = [t.name for t in agent_tools]
        assert "code_executor" not in names

    def test_code_executor_schema_generation(self):
        registry = ToolRegistry()
        registry.discover(_TOOLS_DIR)
        schemas = registry.generate_schemas()
        ce_schema = next(
            (s for s in schemas if s["function"]["name"] == "code_executor"),
            None,
        )
        assert ce_schema is not None
        assert ce_schema["type"] == "function"
        params = ce_schema["function"].get("parameters", {})
        assert "code" in params.get("properties", {})

    def test_no_scaffold_tools_remain(self):
        """Scaffold example tools (web_search, format_citations) must not be present."""
        registry = ToolRegistry()
        discovered = registry.discover(_TOOLS_DIR)
        names = [t.name for t in discovered]
        assert "web_search" not in names
        assert "format_citations" not in names


# ---------------------------------------------------------------------------
# Test: system prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_loads(self):
        loader = PromptLoader()
        loader.load_all(_PROMPTS_DIR)
        assert "system" in loader.names

    def test_system_prompt_metadata(self):
        loader = PromptLoader()
        loader.load_all(_PROMPTS_DIR)
        prompt = loader.get("system")
        assert prompt.name == "system"
        assert prompt.description == "System prompt for the Calculus Helper agent"

    def test_system_prompt_mentions_calculus(self):
        loader = PromptLoader()
        loader.load_all(_PROMPTS_DIR)
        rendered = loader.render("system")
        assert "Calculus Helper" in rendered

    def test_system_prompt_mentions_tools(self):
        loader = PromptLoader()
        loader.load_all(_PROMPTS_DIR)
        rendered = loader.render("system")
        assert "integration" in rendered.lower()
        assert "differentiation" in rendered.lower()

    def test_system_prompt_mentions_code_executor(self):
        loader = PromptLoader()
        loader.load_all(_PROMPTS_DIR)
        rendered = loader.render("system")
        assert "code_executor" in rendered

    def test_system_prompt_has_no_variables(self):
        """The calculus prompt has no template variables."""
        loader = PromptLoader()
        loader.load_all(_PROMPTS_DIR)
        prompt = loader.get("system")
        assert len(prompt.variables) == 0


# ---------------------------------------------------------------------------
# Test: summarize skill (scaffold artifact, still present)
# ---------------------------------------------------------------------------


class TestSummarizeSkill:
    def test_skill_discovered(self):
        loader = SkillLoader()
        loader.load_all(_SKILLS_DIR)
        assert "summarize" in loader

    def test_skill_metadata(self):
        loader = SkillLoader()
        loader.load_all(_SKILLS_DIR)
        manifest = loader.get_manifest()
        entry = next((e for e in manifest if e.name == "summarize"), None)
        assert entry is not None
        assert "summarize" in entry.triggers
        assert entry.description

    def test_skill_activation(self):
        loader = SkillLoader()
        loader.load_all(_SKILLS_DIR)
        skill = loader.activate("summarize")
        assert skill.activated
        assert skill.content is not None
        assert "Summarize Skill" in skill.content


# ---------------------------------------------------------------------------
# Test: citation_required rule (scaffold artifact, still present)
# ---------------------------------------------------------------------------


class TestCitationRule:
    def test_rule_loads(self):
        from fipsagents.baseagent.rules import RuleLoader

        loader = RuleLoader()
        loader.load_all(_RULES_DIR)
        rule = loader.get("citation_required")
        assert rule.name == "citation_required"

    def test_rule_content(self):
        from fipsagents.baseagent.rules import RuleLoader

        loader = RuleLoader()
        loader.load_all(_RULES_DIR)
        rule = loader.get("citation_required")
        assert "citation" in rule.content.lower()
