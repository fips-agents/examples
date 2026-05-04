# 7. Extend with AI

Your agent has two calculus tools, a code sandbox, and a chat UI. It works,
but it only covers integration and differentiation. The full calculus-helper
MCP server has eight tools. You could write the remaining six by hand, but
there's a faster way: use Claude Code's slash commands to plan, generate,
test, and deploy new tools in minutes. In this module you'll walk through
that workflow and learn how to extend the agent side with skills.

## The slash command workflow

Claude Code supports **slash commands** -- reusable instructions stored as
Markdown files in `.claude/commands/`. When you type `/plan-tools` in Claude
Code, it reads the corresponding Markdown file and executes the instructions
inside it. There's nothing magic about them: they're just prompt templates
that encode a development workflow.

The MCP server template ships with four commands that form a pipeline:

```text
/plan-tools         Creates TOOLS_PLAN.md (planning only, no code)
      |
/create-tools       Generates and implements tools in parallel
      |
/exercise-tools     Tests ergonomics by role-playing as the consuming agent
      |
/deploy-mcp         Deploys to OpenShift (optional)
```

Each step produces an artifact the next step consumes. You run them in order,
reviewing output between steps.

## Plan new tools

Open Claude Code in the `calculus-helper` directory and run:

```bash
/plan-tools
```

!!! warning "Run this from inside `calculus-helper/`, not `calculus-agent/`"
    These slash commands ship in `calculus-helper/.claude/commands/` and only
    exist when Claude Code is launched with `calculus-helper/` as its working
    directory. If you run `/plan-tools` from `calculus-agent/`, Claude Code
    will report "command not found" or, worse, scaffold a tool into the wrong
    project. If the command isn't recognized, double-check `pwd` and confirm
    `.claude/commands/plan-tools.md` exists in the current directory --
    fips-agents-scaffolded MCP servers ship with these commands, but a
    hand-rolled clone won't.

The command does three things:

1. Reads Anthropic's [tool design article](https://www.anthropic.com/engineering/writing-tools-for-agents) to ground itself in best practices
2. Reads your project's existing code and documentation for context
3. Creates `TOOLS_PLAN.md` with detailed specifications for each tool

You'll have a conversation with Claude Code about what tools to add. For the
calculus-helper, the six new tools are:

- **evaluate_limit** -- limits at a point or infinity, one-sided or two-sided
- **taylor_series** -- Taylor/Maclaurin expansion to a specified order
- **solve_equation** -- symbolic and numerical root finding
- **solve_ode** -- ordinary differential equations with optional initial conditions
- **simplify_expression** -- rewrite expressions (expand, factor, collect, trigsimp)
- **evaluate_numeric** -- substitute values and compute to specified precision

The plan specifies parameters, return types, error cases, and example usage
for each tool -- the same level of detail as a good API design doc. See
`calculus-helper/TOOLS_PLAN.md` in the repo for the full plan that was used
to build the reference implementation.

!!! tip "Review the plan before proceeding"
    `/plan-tools` deliberately produces no code. Review `TOOLS_PLAN.md`
    carefully -- parameter names, error messages, and return shapes are much
    harder to change after implementation. This is where you catch design
    issues like confusing parameter names or missing edge cases.

## Create tools

With the plan approved, run:

```bash
/create-tools
```

The command reads `TOOLS_PLAN.md` and works through each tool:

1. Scaffolds the file with `fips-agents generate tool <name> --async --with-context`
2. Implements the logic based on the plan specification
3. Writes tests in `tests/`
4. Runs `make test` and `make lint` to verify

For six tools, this takes a few minutes. The command launches parallel
subagents (one per tool) to implement them simultaneously, then aggregates
the results and runs the full test suite.

Each generated tool follows the same pattern established by `integrate` and
`differentiate` in Module 3: `Annotated` fields with descriptions, a
`ctx: Context = None` parameter for MCP context logging, tool annotations
declaring idempotent read-only behavior, and the shared `parse_expression` /
`format_result` helpers from `src/calc.py`. See `calculus-helper/src/tools/`
in the repo for all eight implementations.

!!! note "All six tools reuse the shared parsing layer"
    The `src/calc.py` module you built in Module 3 handles expression parsing,
    safe namespace enforcement, and result formatting for every tool. New tools
    only implement their specific math logic -- the boilerplate is shared.

## Exercise tools

Before deploying, test whether the tools are actually pleasant to use from
an agent's perspective:

```bash
/exercise-tools
```

This command role-plays as the consuming agent. It reads the tool schemas and
descriptions, then tries to accomplish realistic tasks:

**Basic usage.** Can the agent figure out how to call the tool from its
description alone? Are parameter names unambiguous?

**Error recovery.** When the agent passes bad input, does the error message
explain what went wrong and how to fix it? A message like `"Use '**' not '^'
for exponents"` is actionable. A raw Python traceback is not.

**Tool composition.** Can the agent chain tools together? For example: find
critical points by differentiating, then solve the resulting equation, then
evaluate the original function at those points.

The command generates eval cases in `evals/evals.yaml` that capture these
scenarios. You can re-run them later with `make eval` as a regression suite.

!!! warning "Ergonomic issues found here are cheap to fix"
    A confusing parameter name caught during exercise costs minutes to rename.
    The same issue caught after deployment means updating every agent that
    uses the tool, plus retraining users who've learned the old name.

## Deploy the updated MCP server

With all eight tools passing tests and exercised for ergonomics, deploy:

```bash
./deploy.sh calculus-mcp
```

Or using the Makefile:

```bash
make deploy PROJECT=calculus-mcp
```

The deployment rebuilds the container image and rolls out the new pod. The
agent discovers the new tools automatically at its next restart -- **no
agent-side code changes needed**. This is the MCP value proposition from
Module 4: the agent connects to the MCP server, discovers tool schemas, and
registers them. When you add tools to the server, the agent picks them up.

Restart the agent to trigger discovery:

```bash
oc rollout restart deployment/calculus-agent -n calculus-agent
```

Verify the agent sees all eight tools:

```bash
ROUTE=$(oc get route calculus-agent -n calculus-agent -o jsonpath='{.spec.host}')
curl -sk "https://$ROUTE/v1/agent-info" | python -m json.tool
```

```json
{
    "name": "calculus-agent",
    "version": "0.1.0",
    "tools": [
        "integrate", "differentiate", "evaluate_limit",
        "taylor_series", "solve_equation", "solve_ode",
        "simplify_expression", "evaluate_numeric", "code_executor"
    ]
}
```

## Update the system prompt

The agent discovers tool schemas automatically, but the system prompt should
still describe the full range of capabilities so the LLM knows when to reach
for each one. Open `prompts/system.md` in the agent project and add sections
for each new capability area: limits, Taylor series, equation solving, ODE
solving, simplification, and numeric evaluation. List them alongside the
existing integration, differentiation, and code execution sections.

The key additions to the `## Instructions` section:

```markdown
3. Chain tools when needed -- e.g., differentiate then solve for critical points.
4. Use `simplify_expression` to clean up intermediate results before presenting.
5. Use `evaluate_numeric` or the code sandbox for decimal follow-up,
   not as a replacement for symbolic tools.
```

!!! info "The prompt describes capabilities, not schemas"
    BaseAgent injects tool schemas into the system message at runtime.
    The prompt's job is to describe the domain, guide tool selection, and set
    behavioral expectations. It shouldn't duplicate what the schemas already
    communicate.

## Add a skill

Skills are capabilities with their own instructions that are too large to
keep in context permanently. Unlike tools (which are functions) or prompts
(which are templates), skills carry behavioral instructions, references, and
examples that load only when activated.

Switch to the agent project and run:

```bash
/add-skill
```

Claude Code will ask what the skill does. For example, a "summarize" skill
that condenses long outputs into executive briefs. The command creates a
directory under `skills/` with a `SKILL.md` file:

```
skills/summarize/
  SKILL.md
```

The `SKILL.md` file uses YAML frontmatter for metadata (`name`,
`description`, `triggers`, `parameters`) and Markdown for behavioral
instructions. See `calculus-agent/skills/summarize/SKILL.md` in the repo for
a complete example.

Skills follow the **progressive disclosure** pattern from the agentskills.io
spec. At startup, `build_system_prompt()` loads only the frontmatter from
each skill (~100 tokens) and appends it to the system prompt as a manifest.
The LLM sees that the skill exists and what triggers it, but doesn't pay the
context cost of the full instructions until the skill is activated.

!!! tip "When to use a skill vs. a tool vs. a prompt"
    **Tool**: a function that takes input and returns output. Use for
    discrete operations (integrate, search, format).
    **Prompt**: a template that shapes LLM behavior for a specific task.
    **Skill**: a capability with its own multi-step instructions, references,
    or examples that would bloat the system prompt if always loaded. Use for
    complex behaviors like "summarize a research paper" or "generate a
    lesson plan."

## How slash commands work

The commands used in this module are not built into Claude Code. They're
Markdown files in `.claude/commands/`:

```
calculus-helper/.claude/commands/
  plan-tools.md
  create-tools.md
  exercise-tools.md
  deploy-mcp.md
```

Each file has YAML frontmatter with a `description` field and a Markdown
body with step-by-step instructions. For example, `plan-tools.md` tells
Claude Code to read Anthropic's tool design article, examine the project
context, create `TOOLS_PLAN.md`, and present the plan for review. The body
is explicit about what to do and what not to do ("this is a discussion and
planning phase only -- do NOT implement any code").

When you type `/plan-tools`, Claude Code reads this file and follows its
instructions. That's all there is to it. You can create your own slash
commands for any repeatable workflow: code review checklists, migration
playbooks, documentation generators, release procedures.

The agent template ships with its own set of commands (`/plan-agent`,
`/create-agent`, `/exercise-agent`, `/add-tool`, `/add-skill`) that follow
the same pattern. Both the MCP server and agent templates encode their
development workflows as slash commands, making them reproducible and
sharable across teams.

!!! info "Creating your own slash commands"
    Create a `.claude/commands/` directory in any project. Add a Markdown
    file with a `description` in the frontmatter and instructions in the
    body. The filename (minus `.md`) becomes the command name. Team members
    who clone the repo get the commands automatically.

## The meta point

Step back and notice what happened in this module. You used an AI tool
(Claude Code) to accelerate the development of AI tools (MCP server tools)
that are consumed by an AI agent. The slash commands encode human expertise
about tool design into reusable instructions that Claude Code executes
consistently.

This is the leverage: instead of writing each tool from scratch, you wrote a
plan and let the toolchain handle scaffolding, implementation, testing, and
deployment. The six new tools took minutes instead of hours, and they follow
the same patterns and quality standards as the two you wrote by hand in
Module 3. When you onboard a new team member, they run the same commands and
get the same results.

## What's next

Your agent now has a full suite of calculus tools, a code sandbox, and
extensible skills. In [Module 8](08-secrets-and-production.md), you'll
harden it for production: FIPS compliance, secrets management, JWT
authentication for the MCP server, resource limits, and monitoring.
