# Server-side middleware recipes

A few TUI features need the connected Deep Agent server to register specific middleware. The TUI works without them, but skips the corresponding affordance silently. This page collects the recipes.

| TUI feature | Server requirement |
|-------------|--------------------|
| Workspace path in the hint bar / banner (without `DEEPAGENT_WORKSPACE`) | A middleware that writes the path into thread state |
| `/compact` slash command | `SummarizationToolMiddleware` (exposes the `compact_conversation` tool) |

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

## See also

- [Threads](threads.md) — how `/rewind` filters out messages cleaned up by `/compact`
- [Commands](commands.md) — the user-facing reference for `/compact`
- [Configuration](configuration.md) — `DEEPAGENT_WORKSPACE` env var
