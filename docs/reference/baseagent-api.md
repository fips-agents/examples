# BaseAgent API

Complete method reference for `BaseAgent`, the base class your agent
subclasses. Import it from `fipsagents.baseagent`:

```python
from fipsagents.baseagent import BaseAgent, StepResult
```

Your agent implements `step()`. Everything else is inherited.


## Lifecycle

These methods control how an agent starts, runs, and stops. You rarely call
them directly -- the HTTP server manages the lifecycle for each request.

### start

```python
async def start() -> str
```

Full lifecycle entry point: calls `setup()`, then `run()`, then `shutdown()`
with guaranteed cleanup. Returns the final response content. This is the
recommended way to execute an agent programmatically.

### setup

```python
async def setup() -> None
```

Called once before the agent loop begins. Loads configuration, connects to
MCP servers, discovers tools, loads prompts, and builds the system message.
Override this to add custom initialization (always call `await super().setup()`
first).

### step

```python
async def step() -> StepResult
```

Called repeatedly inside `run()`. Each invocation is one turn of reasoning.
This is the method you implement in your subclass.

Return `StepResult.done(result)` to end the loop, or
`StepResult.continue_()` to run another iteration.

```python
class MyAgent(BaseAgent):
    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(response.content)
```

### run

```python
async def run() -> str
```

Calls `step()` in a loop until it returns `StepResult.done()` or
`max_iterations` (from `agent.yaml`) is reached. Returns the final content.
Applies exponential backoff on retryable errors using the `loop.backoff`
settings.

### shutdown

```python
async def shutdown() -> None
```

Called once after the loop ends (even if `step()` raised). Closes MCP
connections and releases resources. Override to add custom teardown (always
call `await super().shutdown()` last).


## LLM Methods

All model interaction goes through these methods. Do not import the `openai`
library directly.

### call_model

```python
async def call_model(
    messages: list[dict] | None = None,
    *,
    tools: list[dict] | None = None,
    include_tools: bool = True,
    **kw,
) -> ModelResponse
```

Send a completion request to the LLM. Defaults to `self.messages` for the
conversation and `self.get_tool_schemas()` for the tool list. Returns a
`ModelResponse` with `.content` (str) and `.tool_calls` (list).

```python
response = await self.call_model()                          # defaults
response = await self.call_model(include_tools=False)       # no tool schemas
response = await self.call_model(messages=[                 # one-off messages
    {"role": "user", "content": "Summarize this text."}
])
```

### call_model_json

```python
async def call_model_json(
    schema: type[BaseModel] | dict,
    messages: list[dict] | None = None,
    **kw,
) -> ModelResponse
```

Request structured output. `schema` is a Pydantic model class or a JSON
Schema dict. The LLM response is constrained to match the schema.

```python
from pydantic import BaseModel

class Analysis(BaseModel):
    topic: str
    confidence: float
    summary: str

response = await self.call_model_json(Analysis)
result = Analysis.model_validate_json(response.content)
```

### call_model_stream

```python
async def call_model_stream(
    messages: list[dict] | None = None,
    **kw,
) -> AsyncIterator[str]
```

Returns an async iterator of content chunks. Use this when you need to stream
a response token-by-token (for example, to a UI).

```python
async for chunk in self.call_model_stream():
    print(chunk, end="", flush=True)
```

### call_model_validated

```python
async def call_model_validated(
    validator_fn: Callable[[ModelResponse], T],
    messages: list[dict] | None = None,
    *,
    max_retries: int = 3,
    **kw,
) -> T
```

Call the model, then pass the response through `validator_fn`. If the
validator raises an exception, the call is retried with exponential backoff up
to `max_retries` times. Returns the validator's return value on success.

```python
def validate_has_answer(response):
    if "I don't know" in response.content:
        raise ValueError("Model declined to answer")
    return response.content

answer = await self.call_model_validated(validate_has_answer, max_retries=2)
```


## Tool Methods

### run_tool_calls

```python
async def run_tool_calls(response: ModelResponse) -> ModelResponse
```

Execute all tool calls from a model response, append results to the
conversation, and re-call the model. Repeats until no tool calls remain.
Works identically for local and MCP-discovered tools. For custom per-tool
error handling, use the manual dispatch pattern in `CLAUDE.md`.

```python
async def step(self) -> StepResult:
    response = await self.call_model()
    response = await self.run_tool_calls(response)
    return StepResult.done(response.content)
```

### use_tool

```python
async def use_tool(name: str, **kwargs) -> ToolResult
```

Call a tool from agent code (plane 1). The tool must have visibility
`agent_only` or `both`. Do not use this for LLM-initiated tool calls --
those go through `run_tool_calls()` or `self.tools.execute()`.

```python
result = await self.use_tool("validate_input", text=user_input)
if result.error:
    self.add_message("assistant", f"Invalid input: {result.error}")
```

### get_tool_schemas

```python
def get_tool_schemas() -> list[dict]
```

Returns OpenAI-compatible tool schemas for all tools visible to the LLM
(`llm_only` and `both`). Called automatically by `call_model()` when
`include_tools=True`.


## MCP Methods

BaseAgent connects to MCP servers listed in `agent.yaml` during `setup()`.
Tools are auto-registered. Prompts and resources are available through these
methods.

### connect_mcp

```python
async def connect_mcp(server_url: str) -> None
```

Connect to an MCP server at runtime. Discovers tools (registered as
`llm_only`), prompts, and resources. Called automatically for each
`mcp_servers:` entry during `setup()`; call it directly only when connecting
to a server discovered at runtime.

```python
await self.connect_mcp("http://search-mcp:8080/mcp")
```

### get_mcp_prompt

```python
async def get_mcp_prompt(name: str, arguments: dict | None = None) -> str
```

Render a prompt template from a connected MCP server.

```python
prompt = await self.get_mcp_prompt("analysis", {"topic": "derivatives"})
self.add_message("user", prompt)
```

### read_resource

```python
async def read_resource(uri: str) -> str
```

Read a resource exposed by a connected MCP server. Resources are identified
by URI.

```python
content = await self.read_resource("docs://calculus/integration-rules")
```

### list_mcp_prompts

```python
async def list_mcp_prompts() -> list[PromptInfo]
```

List all prompts available from connected MCP servers.

### list_mcp_resources

```python
async def list_mcp_resources() -> list[ResourceInfo]
```

List all resources available from connected MCP servers.

### list_mcp_resource_templates

```python
async def list_mcp_resource_templates() -> list[ResourceTemplateInfo]
```

List resource templates. Templates are parameterized URIs that generate
resources dynamically (e.g., `docs://{topic}/summary`).


## Prompt Methods

### build_system_prompt

```python
def build_system_prompt() -> str
```

Assembles the full system prompt from three sources: the system prompt file
(`prompts/system.md` by default), all rule files from `rules/`, and the skill
manifest (frontmatter from each `skills/*/SKILL.md`). Called automatically
during `setup()`. Override to inject dynamic content.

### load_prompt

```python
async def load_prompt(name: str, **variables) -> str
```

Load a prompt template from the `prompts/` directory by name (without the
`.md` extension) and substitute `{variable_name}` placeholders.

```python
prompt = await self.load_prompt("summarize", document=text, max_length="200 words")
self.add_message("user", prompt)
response = await self.call_model()
```

See [Module 1](../01-scaffold-agent.md#project-structure) for prompt file
format (Markdown with YAML frontmatter).


## Message Methods

BaseAgent maintains a conversation history in `self.messages`, a list of
OpenAI-format message dicts.

### add_message

```python
def add_message(role: str, content: str) -> None
```

Append a message to the conversation history.

```python
self.add_message("user", "What is the derivative of x^3?")
self.add_message("assistant", "The derivative of x^3 is 3x^2.")
```

### get_messages

```python
def get_messages() -> list[dict]
```

Return the current conversation history.

### clear_messages

```python
def clear_messages() -> None
```

Reset the conversation history to empty. The system prompt is re-injected on
the next `call_model()` invocation.


## StepResult

Returned by `step()` to signal whether the agent loop should continue or stop.

### StepResult.done

```python
StepResult.done(result: str) -> StepResult
```

Stop the loop. `result` becomes the final response content.

### StepResult.continue_

```python
StepResult.continue_() -> StepResult
```

Continue to the next `step()` iteration. Use this when the agent needs
multiple reasoning turns before producing a final answer.

```python
if self.needs_more_research(response):
    self.add_message("user", "Please verify that result.")
    return StepResult.continue_()
return StepResult.done(response.content)
```


## Server HTTP API

BaseAgent itself has no concept of sessions, traces, or metrics -- these are
server-layer concerns handled by `OpenAIChatServer`. The server wraps your
agent subclass and exposes an OpenAI-compatible HTTP surface with optional
observability features. See the
[agent.yaml reference](agent-yaml.md) for
server configuration options.


### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz` | GET | Health check. Returns `{"status": "ok"}`. |
| `/readyz` | GET | Readiness check. Returns `{"status": "ready"}` when initialized, 503 otherwise. |
| `/v1/agent-info` | GET | Agent metadata (name, description, version, model, tools, MCP servers). |
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions. Supports `stream: true/false`. Optional `session_id` field for session persistence. |


### Session Endpoints

Requires `server.sessions.enabled: true` in `agent.yaml`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/sessions` | POST | Create a session. Body: `{"session_id": "my-session"}`. Returns 201. |
| `/v1/sessions/{id}` | GET | Retrieve session with message history. |
| `/v1/sessions/{id}` | DELETE | Delete a session. |

Sessions are also auto-created on first use -- pass `session_id` on any
`/v1/chat/completions` request and the server will create the session if it
does not already exist. The `save()` method uses upsert semantics, so the
explicit `POST /v1/sessions` endpoint is optional but recommended when you
need to control the session ID or check for duplicates.


### Trace Endpoints

Requires `server.traces.enabled: true` in `agent.yaml`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/traces` | GET | List traces (most recent first). Each entry includes `trace_id`, `started_at`, `duration_ms`, `span_count`, `tool_calls`, `model`, `session_id`, and `status`. |
| `/v1/traces/{id}` | GET | Get a single trace with the full span tree. |


### Metrics Endpoint

Requires `server.metrics.enabled: true` in `agent.yaml`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/metrics` | GET | Prometheus text format metrics. Counters: `agent_requests_total`, `agent_tool_call_total`, `agent_tokens_total` (labels: `model`, `direction`; values: `prompt`, `completion`). Histograms: `agent_request_duration_seconds`, `agent_model_call_duration_seconds`. |
