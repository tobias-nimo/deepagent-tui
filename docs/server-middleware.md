# Server-side middleware recipes

A few TUI features need the connected Deep Agent server to register specific middleware. The TUI works without them, but skips the corresponding affordance silently. This page collects the recipes.

| TUI feature | Server requirement |
|-------------|--------------------|
| Workspace path in the hint bar / banner (without `DEEPAGENT_WORKSPACE`) | A middleware that writes the path into thread state |
| `/compact` slash command | `SummarizationToolMiddleware` (exposes the `compact_conversation` tool) |
| `/settings` → Harness tab: `Tools`, `Subagents` rows | `agent_info_middleware` (writes `tools` / `subagents` into thread state) |
| `/settings` → Usage tab: context-capacity meter, server-priced cost | `llm_info_middleware` (writes `context_window` / `input_price_per_mtok` / `output_price_per_mtok` into thread state) |

Each section below is a self-contained recipe; pick the ones you need.

## Workspace path

The TUI's hint bar shows the agent's workspace path. When `DEEPAGENT_WORKSPACE` is unset, the TUI reads the path from LangGraph thread state — the server is the authority.

### What the TUI reads

After every assistant turn, the TUI calls `client.get_thread_state(thread_id)` and scans `values` for the first absolute-path string under one of:

```
working_directory, workspace, project_root, root_dir, cwd, workspace_dir
```

Non-absolute values (anything not starting with `/`) are ignored. `root_dir` is the recommended key — it's the same name `LocalShellBackend` (and other backends) already uses for its working directory parameter.

### The middleware

The cleanest hook is `abefore_agent` on a custom middleware: it runs once at the start of each agent invocation, before the first model call, and any dict it returns is merged into thread state.

```python
# src/middleware/workspace_state.py
from typing import Any, NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langgraph.runtime import Runtime


class WorkspaceState(AgentState):
    """Adds the agent's workspace root_dir to the public state schema."""

    root_dir: NotRequired[str]


class WorkspaceStateMiddleware(AgentMiddleware[WorkspaceState, Any, Any]):
    """Seeds the backend's root_dir into thread state on first invocation."""

    state_schema = WorkspaceState

    def __init__(self, root_dir: str) -> None:
        self._root_dir = root_dir

    async def abefore_agent(
        self, state: WorkspaceState, runtime: Runtime
    ) -> dict[str, Any] | None:
        if state.get("root_dir") == self._root_dir:
            return None
        return {"root_dir": self._root_dir}
```

Two things to note:

- **The state schema must declare `root_dir`.** Returning a key that isn't in the schema gets silently dropped — that's the most common reason "it didn't appear in `get_state`". Subclass `AgentState` and add the field (any of the six keys above works).
- **The check makes the hook idempotent.** It returns `None` after the value is already in state, so subsequent turns don't churn the checkpointer.

### Wiring it in

Pass an instance into `middleware=[...]` on `create_deep_agent()` and source the value from your backend, not a hardcoded constant — that way it tracks `LocalShellBackend(root_dir=...)` automatically:

```python
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from .middleware import WorkspaceStateMiddleware

backend = LocalShellBackend(root_dir="/path/to/workspace", ...)

agent = create_deep_agent(
    model=...,
    backend=backend,
    middleware=[WorkspaceStateMiddleware(str(backend.cwd))],
    # ... other args
)
```

`backend.cwd` is the resolved absolute path the backend actually treats as its working directory (`LocalShellBackend.__init__` does `self.cwd = Path(root_dir).resolve()`), so it's guaranteed to satisfy the TUI's "must start with `/`" check.

### Verifying

After any thread is created and the first turn lands, `get_state` should include `root_dir`:

```python
state = await client.threads.get_state(thread_id)
assert state["values"]["root_dir"].startswith("/")
```

In the TUI, the welcome banner and the hint bar will pick it up the next time `_discover_from_thread_state` runs (immediately after the first assistant turn on a fresh thread).

### Why not other approaches

- **Initial-state seed on the graph.** `create_deep_agent` returns a compiled graph; there's no clean place to inject an initial state dict for every thread without re-wrapping the graph.
- **Assistant metadata.** Read at startup with different caching semantics; the TUI's authoritative path is per-thread state, so metadata wouldn't update if the server's workspace changes between sessions.
- **Environment variable only.** `LocalShellBackend(env={"WORKSPACE_ROOT": ...})` is still useful (tools running in the subshell see it), but it's not visible to LangGraph clients — keep both.

## Conversation compaction

The `/compact` slash command tells the agent to summarise older messages and reclaim context window space. It works by asking the agent to invoke its `compact_conversation` tool — which is only registered when `SummarizationToolMiddleware` is in the middleware list. Without it, `/compact` falls back to a "tool not registered" error.

### The middleware

`create_summarization_tool_middleware` is the convenience factory: it builds a `SummarizationMiddleware` (the engine) and wraps it in a `SummarizationToolMiddleware` (the tool surface) with model-aware defaults.

```python
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.summarization import (
    create_summarization_tool_middleware,
)

model = "anthropic:claude-sonnet-4-6"

agent = create_deep_agent(
    model=model,
    middleware=[
        create_summarization_tool_middleware(model, StateBackend),
        # ...other middlewares
    ],
)
```

You get three things:

- The `compact_conversation` tool, which the agent (or `/compact`) can call.
- A short system-prompt nudge that hints when to call it.
- An eligibility gate at ~50% of the auto-summarization trigger so the tool refuses to compact too-small conversations.

### How `/compact` uses it

The TUI does **not** inject a synthetic `AIMessage` with a tool call. The eligibility gate at `SummarizationToolMiddleware._is_eligible_for_compaction` reads `usage_metadata.total_tokens` from the most recent AIMessage — and langchain's dict-to-message coercion drops `usage_metadata` when a message is sent over the wire via `update_state`. So an injected tool call would always report 0 tokens and the gate would always deny.

Instead, `/compact` sends a focused user prompt (`"Invoke the compact_conversation tool now …"`) via the normal run-stream path. The model produces the tool call itself with its real `usage_metadata` attached, the gate sees the conversation's true token count, and the tool fires.

The TUI then cleans up every message added during the compact turn (the prompt, the AI tool call, the tool result, and the model's follow-up) via `RemoveMessage` — so no trace remains in the conversation. On success, the summary survives in `_summarization_event` state and is applied to subsequent model runs by the middleware.

### Why "Nothing to compact yet"

The eligibility gate sits at roughly half of the configured auto-summarization trigger:

- Default trigger: `("fraction", 0.85)` — auto-summarises at 85% of `max_input_tokens`. Gate at ~42.5%.
- No-profile fallback: `("tokens", 170_000)`. Gate at ~85_000.

For a small conversation (a few thousand tokens), `/compact` will land on `⎿ Nothing to compact yet — conversation is within the token budget.` That's the middleware refusing, not a bug. The tool will fire once the conversation crosses the gate.

### Pairing with auto-summarization

For *automatic* summarisation at the trigger threshold, also register a `SummarizationMiddleware`. `create_deep_agent` adds one by default, so dropping `create_summarization_tool_middleware(...)` into its `middleware=[...]` gives you both layers; they share state via the `_summarization_event` key.

### Verifying

After the middleware is registered, the assistant's tool list should include `compact_conversation`:

```bash
curl -s http://localhost:2024/assistants/<id>/schemas \
  | python -c "import json,sys; print(json.load(sys.stdin))" \
  | grep -o compact_conversation
```

Or just run `/compact` in the TUI — a non-error outcome line (either `⎿ Summarised N messages …` or `⎿ Nothing to compact yet …`) means the wiring is correct.

## Agent info (tools & subagents)

The `/settings` Harness tab can show the live list of tools bound to the main agent and the names of any registered subagents. Both come from `agent_info_middleware`.

### What the TUI reads

After the first turn lands, the TUI calls `client.get_thread_state(thread_id)` and looks for two keys on `values`:

- `tools: list[str]` — tool names bound to the main agent (deepagent built-ins plus anything you passed in).
- `subagents: list[str]` — names of registered subagents. Subagents aren't exposed as model tools (they're routed via the `task` dispatcher), so they have to be supplied to the middleware explicitly.

Both keys are optional. When the middleware isn't attached, the rows render as `—`.

### The middleware

The middleware auto-detects tool names from the first `ModelRequest` and takes subagent names as a constructor argument. It writes back via `aafter_model`, so the values appear after the first model call completes — not on a brand-new thread before any user message.

```python
# src/middleware/agent_info.py
from typing import Any, NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState, ModelRequest


class _AgentInfoState(AgentState):
    tools: NotRequired[list[str]]
    subagents: NotRequired[list[str]]


class _AgentInfoMiddleware(AgentMiddleware[_AgentInfoState, Any, Any]):
    state_schema = _AgentInfoState

    def __init__(self, subagents: list[dict[str, Any]]) -> None:
        self._subagent_names = [s["name"] for s in subagents]
        self._tool_names: list[str] | None = None

    async def awrap_model_call(self, request: ModelRequest, handler):
        if self._tool_names is None:
            self._tool_names = sorted(
                getattr(t, "name", None) or t.get("name", "")
                for t in (request.tools or [])
            )
        return await handler(request)

    async def aafter_model(self, state, runtime):
        updates: dict[str, Any] = {}
        if self._tool_names is not None and state.get("tools") != self._tool_names:
            updates["tools"] = self._tool_names
        if state.get("subagents") != self._subagent_names:
            updates["subagents"] = self._subagent_names
        return updates or None


def agent_info_middleware(subagents: list[dict[str, Any]]) -> AgentMiddleware:
    return _AgentInfoMiddleware(subagents)
```

### Wiring it in

Pass the same `subagents` list you give to `create_deep_agent`, so the names line up:

```python
from deepagents import create_deep_agent
from .middleware import agent_info_middleware

subagents = [
    {"name": "research", "prompt": "..."},
    {"name": "code-reviewer", "prompt": "..."},
]

agent = create_deep_agent(
    model=...,
    subagents=subagents,
    middleware=[agent_info_middleware(subagents), ...],
)
```

### Verifying

After one turn:

```python
state = await client.threads.get_state(thread_id)
print(state["values"]["tools"])      # e.g. ['edit_file', 'read_file', 'task', ...]
print(state["values"]["subagents"])  # e.g. ['research', 'code-reviewer']
```

## LLM info (context window & pricing)

The `/settings` Usage tab can show a context-capacity meter and a server-priced cost figure. Both come from `llm_info_middleware`.

### What the TUI reads

The TUI looks for three keys on `values`:

- `context_window: int` — max input tokens for the agent's LLM. Drives the `current / max` meter on the Usage tab. The "current" number is the input-token count reported on the **most recent single model call** (a closer proxy to "what's actually in the window now" than cumulative tokens, which would keep growing past the window even after compaction).
- `input_price_per_mtok: float` — USD per 1M input tokens.
- `output_price_per_mtok: float` — USD per 1M output tokens.

When both prices are present, the TUI uses them instead of its hardcoded `MODEL_PRICING` table (`src/deepagent_tui/utils/cost.py`). Cost already accrued under the fallback table is not retroactively recomputed when the override arrives.

When `context_window` is absent, the Usage tab shows `unknown (server middleware not attached)` instead of a meter.

> **Caveat — cost only covers the main agent.**
> `llm_info_middleware` is set up per agent instance, so token usage and pricing only flow back to thread state for the **main agent's** LLM calls. Subagent LLM calls don't increment the TUI's cost counter unless the same middleware is also attached inside each subagent's middleware list (and that subagent's tokens get streamed back to the parent thread, which is the default for in-process subagents).

### The middleware

`llm_info_middleware` is a single-shot writer. Its `abefore_agent` hook seeds the three values into thread state on the first invocation and short-circuits on subsequent turns once they're already present.

```python
# src/middleware/llm_info.py
from typing import Any, NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langgraph.runtime import Runtime


class _LLMInfoState(AgentState):
    context_window: NotRequired[int]
    input_price_per_mtok: NotRequired[float]
    output_price_per_mtok: NotRequired[float]


class _LLMInfoMiddleware(AgentMiddleware[_LLMInfoState, Any, Any]):
    state_schema = _LLMInfoState

    def __init__(
        self,
        context_window: int,
        input_price_per_mtok: float,
        output_price_per_mtok: float,
    ) -> None:
        self._context_window = context_window
        self._input_price = input_price_per_mtok
        self._output_price = output_price_per_mtok

    async def abefore_agent(self, state, runtime):
        if (
            state.get("context_window") == self._context_window
            and state.get("input_price_per_mtok") == self._input_price
            and state.get("output_price_per_mtok") == self._output_price
        ):
            return None
        return {
            "context_window": self._context_window,
            "input_price_per_mtok": self._input_price,
            "output_price_per_mtok": self._output_price,
        }


def llm_info_middleware(
    context_window: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
) -> AgentMiddleware:
    return _LLMInfoMiddleware(context_window, input_price_per_mtok, output_price_per_mtok)
```

### Wiring it in

Sourcing the numbers from the model is what keeps them honest — hardcoding them is the same maintenance burden the TUI is trying to escape.

```python
from deepagents import create_deep_agent
from .middleware import llm_info_middleware

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    middleware=[
        llm_info_middleware(
            context_window=200_000,
            input_price_per_mtok=3.0,
            output_price_per_mtok=15.0,
        ),
        # ...other middlewares
    ],
)
```

To extend cost tracking to subagents, register the middleware inside each subagent's middleware list as well — the TUI doesn't separate per-agent token usage, so this gives a single cumulative figure across the main agent and its subagents.

### Verifying

```python
state = await client.threads.get_state(thread_id)
print(state["values"]["context_window"])         # 200000
print(state["values"]["input_price_per_mtok"])   # 3.0
print(state["values"]["output_price_per_mtok"])  # 15.0
```

In the TUI, open `/settings` and switch to the Usage tab — you should see a filled bar against the configured window, and the Cost row reflects the override prices on the next turn.

## See also

- [Threads](threads.md) — how `/rewind` filters out messages cleaned up by `/compact`
- [Commands](commands.md) — the user-facing reference for `/compact`
- [Configuration](configuration.md) — `DEEPAGENT_WORKSPACE` env var
