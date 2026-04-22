# Next Session: Tutorial Content Completion

## Context

The `fips-agents/examples` repo is set up with MkDocs Material, GitHub Pages deployment, two completed example projects (`calculus-agent/`, `calculus-helper/`), and the first two tutorial modules written. Six modules and five reference pages need content.

Tutorial site: https://fips-agents.github.io/examples/
Repo: https://github.com/fips-agents/examples

## What's done

- Repo created, MkDocs Material configured, GitHub Pages deploying on push
- Module 1: Scaffold Your Agent (~310 lines) — walks through every file in a scaffolded agent
- Module 2: Configure and Deploy (~298 lines) — agent.yaml, Helm chart, BuildConfig, deployment
- `calculus-agent/` — complete working agent configured for MCP calculus tools
- `calculus-helper/` — complete MCP server with 8 SymPy tools
- All placeholder stubs in place so the site builds clean

## What needs writing

### Tutorial modules (in order)

**Module 3: Build an MCP Server** (`docs/03-build-mcp-server.md`)
- `fips-agents create mcp-server calculus-helper --local`
- Walk through scaffolded structure (FastMCP, FileSystemProvider, auto-discovery)
- Build `src/calc.py` shared parsing layer (whitelist namespace, coaching errors)
- Add `integrate.py` tool step by step (parse → SymPy → format_result)
- Add `differentiate.py` tool
- Test locally with pytest
- Deploy to OpenShift via BuildConfig
- Test MCP protocol with curl (initialize handshake, tools/list)
- Reference: `calculus-helper/` in the repo is the finished product

**Module 4: Wire MCP to Agent** (`docs/04-wire-mcp-to-agent.md`)
- Edit agent.yaml: add `mcp_servers:` entry
- Remove mock `web_search` tool (delete tools/web_search.py)
- Update prompts/system.md for calculus
- Simplify src/agent.py using `run_tool_calls()`
- Rebuild and redeploy agent
- Test: "integrate x^2 dx" flows through MCP → SymPy → back to agent
- Key point: agent code barely changed — just config and prompt

**Module 5: Gateway and UI** (`docs/05-gateway-and-ui.md`)
- `fips-agents create gateway` and `fips-agents create ui`
- Walk through Go project structure (minimal — just an HTTP proxy)
- Deploy both, set BACKEND_URL and API_URL
- Test end-to-end in the browser
- Route timeout annotation for agent chains
- Why a gateway exists (auth, rate limiting, multi-agent routing)

**Module 6: Code Execution Sandbox** (`docs/06-code-sandbox.md`)
- What the sandbox is and how it's secured (AST, import hook, Landlock, memory limits)
- Deploy code-sandbox as a standalone service (BuildConfig, Deployment, Service)
- Add `code_executor` tool to agent's `tools/` directory
- Set `SANDBOX_URL` env var in Helm config
- Update system prompt: agent can now write and run Python
- Test: numerical evaluation, data tables with numpy
- Security walkthrough: profiles (minimal vs data-science), what's allowed/blocked
- Exercise: creating a visualization profile with matplotlib
- Key point: symbolic MCP tools + numerical sandbox = composable capabilities

**Module 7: Extend with AI** (`docs/07-extend-with-ai.md`)
- Open Claude Code in the MCP server project
- `/plan-tools` → design taylor_series, solve_equation, etc.
- `/create-tools` → generate them
- `/exercise-tools` → test scenarios
- Deploy updated MCP server — agent picks up new tools automatically
- `/add-skill` on the agent side
- Key point: slash commands are just markdown files in .claude/commands/

**Module 8: Production Hardening** (`docs/08-secrets-and-production.md`)
- FIPS mode: what it is, how to verify (`/proc/sys/crypto/fips_enabled`)
- The litellm→openai migration story (why we did it, what broke)
- Secrets: OpenShift Secrets, mounting via Helm, OPENAI_API_KEY handling
- MCP server JWT auth (auth.py, env vars)
- Security config in agent.yaml (enforce/observe, tool inspection)
- Resource limits and horizontal scaling
- Monitoring: pod logs, health/readiness probes, route timeouts

### Reference pages

**agent.yaml Reference** (`docs/reference/agent-yaml.md`)
- Every section with all fields, defaults, and env vars
- Annotated example showing a fully configured agent.yaml

**Helm Chart Anatomy** (`docs/reference/helm-chart.md`)
- What each template produces
- How values.yaml maps to resources
- ConfigMap checksum annotation trick
- Sandbox sidecar conditional

**Makefile Targets** (`docs/reference/makefile.md`)
- All targets: install, run-local, test, test-cov, eval, lint, build, deploy, redeploy, clean, vendor, update-framework, help
- When to use which

**BaseAgent API** (`docs/reference/baseagent-api.md`)
- All call_model variants with signatures and examples
- run_tool_calls, use_tool, connect_mcp
- get_mcp_prompt, read_resource, list_mcp_*
- build_system_prompt, load_prompt

**MCP Protocol** (`docs/reference/mcp-protocol.md`)
- Tools, prompts, resources explained
- HTTP vs stdio transports
- How auto-discovery works (connect_mcp flow)
- How to test an MCP server with curl

## Writing approach

Each module should be ~250-350 lines. Use MkDocs Material admonitions for
OpenShift concept explanations (progressive disclosure for newcomers).
Code blocks should be copy-pasteable. Second person ("you'll").

The `calculus-helper/` and `calculus-agent/` directories in the repo serve as
the "answer key" — the tutorial walks the student through building what's
already there.

## Cluster state

The ecosystem-test namespace on fips-rhoai has all services running:
- ecosystem-test-agent (calculus agent with MCP + sandbox)
- ecosystem-test-gateway
- ecosystem-test-ui
- ecosystem-test-mcp (scaffolded template MCP server)
- calculus-mcp (calculus-helper MCP server)

These can be used for screenshots or verification during content writing.

## Other session work from today to be aware of

Major changes shipped to fips-agents repos today:

- **fipsagents v0.8.0**: Replaced litellm with openai async SDK (FIPS compliance)
- **fipsagents v0.7.0**: AgentIdentity, ServerConfig, PromptsConfig.system, run_tool_calls()
- **agent-loop template v0.6.0**: All of the above reflected in template
- **fips-agents-cli v0.8.1**: `--vendored` flag, `fips-agents vendor` command, bug fixes
- **Go FIPS issue**: fips-agents/gateway-template#8 tracks stdlib crypto not being OpenSSL-backed
