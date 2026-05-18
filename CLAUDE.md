# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                              # install (incl. dev extras pinned via uv.lock)
uv run deepagent-tui                 # launch the TUI (entry: deepagent_tui.tui:run_tui)
uv run pytest                        # smoke test suite (Textual pilot, no server needed)
uv run pytest tests/test_tui_smoke.py::test_app_boots_and_mounts_core_widgets   # single test
uv run pytest -k slash               # filter by keyword
uv run ruff check                    # lint (line-length 100, py312, rules: E/F/I)
```

`pytest-asyncio` runs in `auto` mode, so `async def test_*` works without decorators. The smoke suite stubs `bootstrap.connect` and `bootstrap.discover_and_register_skills` via an autouse fixture in `tests/test_tui_smoke.py` — no real LangGraph server is required.

## Runtime expectations

The TUI is a client only — it needs a LangGraph Deep Agent server reachable at `LANGGRAPH_URL` (default `http://localhost:2024`). Start one in another terminal with `uv run langgraph dev --no-browser` from the agent project. See `docs/configuration.md` for env vars (`LANGGRAPH_URL`, `GRAPH_ID`, `THREAD_ID`, `LANGSMITH_API_KEY`, `DEEPAGENT_THEME`). Per-directory `.env` is loaded automatically; parent dirs are not searched.

State written outside the repo:
- `~/.deepagent-tui/threads.db` — SQLite thread index (`/resume`)
- `~/.deepagent-tui/theme` — persisted theme (overrides `DEEPAGENT_THEME` on next launch)

## Architecture (the parts that span files)

Full map: `docs/architecture.md`. Big-picture summary:

- **`tui/app.py`** is the `DeepAgentTUI` Textual app — owns the UI, the keystroke handlers, the stream worker, and the ESC-rollback path. Most cross-cutting changes start here.
- **`bootstrap.py`** runs once on `on_mount`: discovers an assistant via `client.AgentClient`, creates or attaches to a thread, registers skills. The smoke tests stub these two entry points.
- **`session.py`** holds the per-run mutable state (assistant_id, graph_id, thread_id, status, message log, token counters, skills). It is passed by reference everywhere; don't shadow it with copies.
- **`handlers/`** is the streaming brain. A user message kicks off `client.stream_message(...)` with `stream_mode=["updates","messages"]` and `stream_subgraphs=True`. `handlers/stream.py` finalizes partial text on `updates`, `handlers/tools.py` turns raw tool-call/result payloads into `FormattedToolCall`/`FormattedToolResult`, and `handlers/interrupt.py` parses HITL interrupts and builds the `Command(resume=...)` payload. Subagent activity arrives as `updates|<namespace>` — `_handle_subagent_update` in `tui/app.py` binds each namespace FIFO to the oldest pending subagent task so `⎿` progress lines land on the right widget.
- **`ui/tool_widgets.py`** renders each tool call inline. Dispatch is by tool name through `_tool_alias` (so `edit_file`, `str_replace_editor`, etc. share a renderer). A widget has a pending state (`○`, dim) that flips to success/error/rejected (`●` in green/red/amber) when the result arrives. To add a tool, add `_call_<n>` and `_result_<n>`, register in `_CALL_RENDERERS`/`_RESULT_RENDERERS`, and alias the source name(s) in `_tool_alias`.
- **`commands/`** is a registry: each module defines a `@command(...)` and is side-effect-imported from `commands/__init__.py`. To add a slash command, drop a new file there and import it.
- **`storage/db.py`** is the only SQLite touchpoint (aiosqlite, `~/.deepagent-tui/threads.db`).

## Deep Agent server contract

The TUI assumes the server: exposes ≥1 assistant via `assistants.search()`, accepts `{"messages":[{"role":"user","content":...}]}` as run input, streams both `updates` and `messages` chunks, supports `stream_subgraphs=True`, and expresses HITL interrupts via LangChain's `HumanInTheLoopMiddleware` (or any dict with `question`/`description`/`options`). `skills_metadata` in thread state powers `/skills`. Tool widgets are best-effort — unknown tools fall through to the generic renderer.

## Conventions

- Python 3.12+, ruff line-length 100, `ignore = ["E501"]` so long strings are tolerated.
- Tests intentionally avoid live streaming and the HITL end-to-end glue (see `docs/testing.md` for what's out of scope and why). When asserting on widget state, query the widget and read its attributes/classes rather than scraping the screen buffer.
