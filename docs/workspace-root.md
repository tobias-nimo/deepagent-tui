# Exposing the workspace root from a deep agent server

The TUI's hint bar shows the agent's workspace path. When `DEEPAGENT_WORKSPACE` is unset, the TUI reads the path from LangGraph thread state — the server is the authority. This page shows how to write it from a `create_deep_agent()` server in a few lines of middleware.

## What the TUI reads

After every assistant turn, the TUI calls `client.get_thread_state(thread_id)` and scans `values` for the first absolute-path string under one of:

```
working_directory, workspace, project_root, root_dir, cwd, workspace_dir
```

Non-absolute values (anything not starting with `/`) are ignored. `root_dir` is the recommended key — it's the same name `LocalShellBackend` (and other backends) already uses for its working directory parameter.

## The middleware

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

## Wiring it in

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

## Verifying

After any thread is created and the first turn lands, `get_state` should include `root_dir`:

```python
state = await client.threads.get_state(thread_id)
assert state["values"]["root_dir"].startswith("/")
```

In the TUI, the welcome banner and the hint bar will pick it up the next time `_discover_from_thread_state` runs (immediately after the first assistant turn on a fresh thread).

## Why not other approaches

- **Initial-state seed on the graph.** `create_deep_agent` returns a compiled graph; there's no clean place to inject an initial state dict for every thread without re-wrapping the graph.
- **Assistant metadata.** Read at startup with different caching semantics; the TUI's authoritative path is per-thread state, so metadata wouldn't update if the server's workspace changes between sessions.
- **Environment variable only.** `LocalShellBackend(env={"WORKSPACE_ROOT": ...})` is still useful (tools running in the subshell see it), but it's not visible to LangGraph clients — keep both.
