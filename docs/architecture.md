# Architecture

How the codebase is laid out and how a single turn flows through it.

## Package map

```
src/deepagent_tui/
├── __main__.py        # `python -m deepagent_tui` entry — calls run_tui()
├── bootstrap.py       # Startup: discover assistant, attach to thread, register skills
├── config.py          # pydantic-settings — env + .env loading
├── client.py          # AgentClient: thin wrapper around the LangGraph SDK
├── session.py         # Session dataclass — mutable per-run state
├── tui/
│   ├── app.py         # DeepAgentTUI Textual app — the main UI
│   ├── screens.py     # PickerScreen (/resume, /rewind, /skills), HelpScreen (/help), CommandsScreen (/commands), SettingsScreen (/settings)
│   └── inline_approval.py  # InlineApproval widget for HITL prompts
├── ui/
│   ├── renderer.py    # render_info/render_error/render_renderable — ⎿ corner blocks via a mount sink installed by the TUI
│   ├── markdown.py    # render_markdown — themed Rich Markdown
│   ├── tool_widgets.py  # Per-tool inline widgets (Edit, Read, Bash, Todos, etc.)
│   └── theme.py       # 8 themes + persistence + markdown style overrides
├── commands/
│   ├── __init__.py    # @command registry + dispatch
│   ├── builtins.py    # /commands (CommandsScreen) /clear /exit
│   ├── help.py        # /help (opens HelpScreen)
│   ├── new.py         # /new
│   ├── resume.py      # /resume
│   ├── rewind.py      # /rewind
│   ├── compact.py     # /compact (TUI intercepts; routes through _submit_compact)
│   ├── copy.py        # /copy + shared transcript/clipboard helpers
│   ├── export.py      # /export
│   ├── theme.py       # /theme
│   └── skills.py      # /skills and /skills refresh
├── handlers/
│   ├── stream.py      # StreamState + process_messages_event / process_updates_event
│   ├── tools.py       # FormattedToolCall / FormattedToolResult + parsers
│   └── interrupt.py   # InterruptInfo + extract_interrupts + build_resume_value
├── storage/
│   └── db.py          # SQLite thread index (aiosqlite)
└── utils/
    ├── tokens.py      # extract_usage(msg) → (input, output)
    ├── cost.py        # MODEL_PRICING + compute_cost + format_cost/format_tokens
    └── images.py      # Path detection, base64 encoding, terminal protocols
```

## A turn, end to end

A normal user message goes through this path:

1. **`ChatTextArea.Submitted`** fires when the user presses `Enter`. `on_chat_text_area_submitted` extracts image paths, mounts the user's message bubble, and snapshots state for the ESC-rollback path.

2. **Command vs. message split** — if the text starts with `/`, it goes to `_run_command`; otherwise it goes to `_submit_message` as a stream worker.

3. **`_submit_message`** sets `session.status = "streaming"`, mounts a "Thinking…" slot, and calls `client.stream_message(thread_id, assistant_id, content)` with `stream_mode=["updates", "messages"]` and `stream_subgraphs=True`.

4. **`_consume_stream`** dispatches each chunk by its event type:
   - `metadata` — captures the `run_id` so ESC can roll back server-side
   - `messages/partial` — appends streaming text tokens to the active slot (parent agent only; subagent text is suppressed)
   - `updates` — finalizes the streaming slot, then renders tool calls and tool results as inline widgets. Subagent updates (`updates|<ns>`) become `⎿` progress lines on the parent task widget.

5. **`_handle_interrupts`** polls `get_thread_state` after the stream ends. If `state.tasks[*].interrupts` is non-empty, it mounts an `InlineApproval`, waits for the user's choice, and calls `client.resume(...)` with a `Command(resume=...)` payload. Loops until no pending interrupts remain.

6. **`_flush_usage`** accumulates token counts and triggers `_discover_from_thread_state` to register newly-loaded skills as slash commands and (if not pre-set via `DEEPAGENT_WORKSPACE`) read the workspace path from thread state.

7. **`upsert_thread`** updates the local SQLite row with the new `last_message` and `message_count`.

## Key seams

| Want to add a… | Where to look |
|----------------|---------------|
| New slash command | `commands/<name>.py` + `@command(...)` + side-effect import in `commands/__init__.py` |
| New tool widget | `ui/tool_widgets.py` — add a `_call_<n>` and `_result_<n>`, register in `_CALL_RENDERERS` / `_RESULT_RENDERERS`. Alias names in `_tool_alias`. |
| New theme | `THEMES` dict in `ui/theme.py` |
| New picker-based command | Build `PickerItem` list, call `session.picker(items, heading)` |
| New env var | `Settings` class in `config.py` |
| New model pricing | `MODEL_PRICING` in `utils/cost.py` |

## Streaming layers

The TUI relies on two LangGraph SDK stream modes simultaneously:

- **`messages`** — token-level chunks; emitted as `messages/partial`. Used to stream the parent agent's text into the active response slot.
- **`updates`** — node-level updates; emitted as `updates`. Used to surface tool calls and tool results as widgets, capture token usage, and detect when the parent text needs to be finalized.

With `stream_subgraphs=True`, subagent activity is suffixed with `|<namespace>` (e.g. `updates|tools:abc123`). The TUI binds each namespace to the oldest pending subagent call (FIFO matches sequential dispatch) so `⎿` progress lines land on the right widget. See `_handle_subagent_update` in `tui/app.py`.

## ESC rollback

Pressing `Esc` while a stream is in flight calls `_cancel_and_rollback`:

1. Asks the server to roll the run back (`runs.cancel(thread_id, run_id, action="rollback", wait=False)`) — fire-and-forget so the UI doesn't block on network.
2. Cancels the local stream worker (raises `CancelledError` inside `_consume_stream`).
3. Removes every widget mounted after `_turn_start_index` — the user bubble, tool call/result panels, partial assistant text, the thinking slot.
4. Pops the user message from `session.messages`.
5. Restores the raw input (with any newlines) back into the chat bar, re-stages the attachments, and refocuses the prompt.

## `/compact` flow

`/compact` is the only built-in slash command that has to drive the streaming pipeline. The TUI intercepts it in `_run_command` (before `dispatch_command`) and routes through `_submit_compact()`:

1. Snapshot `len(state.messages)` as the baseline.
2. Mount a dim animated `⎿ Compacting…` placeholder (timer cycles 0–3 dots).
3. Call `client.compact_thread(...)`, which sends `"Invoke the compact_conversation tool now …"` as a user prompt and streams the response. We drain the stream silently — `process_updates_event` runs only for token accounting; no widgets are mounted.
4. Fetch the final state, find the `compact_conversation` tool message in the messages added since the baseline, parse its content to decide success vs gate-denied.
5. Remove **every** message added during the turn via `RemoveMessage` (wire format: `{"role":"remove","content":"","id":<id>}`). On success, the summary survives in `_summarization_event`.
6. Replace the placeholder with `⎿ Summarised N messages …` or `⎿ Nothing to compact yet …`.

Why a user prompt and not synthetic AIMessage injection? `_is_eligible_for_compaction` reads `usage_metadata.total_tokens` from the latest AIMessage, and langchain's dict-to-message coercion drops `usage_metadata` when a message reaches the server over the wire. A natural model-produced AIMessage carries `usage_metadata` intact; an injected one always reports 0 tokens and the gate always denies. See [server-middleware.md](server-middleware.md#conversation-compaction).

Side effect: `/rewind` filters its picker by IDs that still exist in current state, so the internal compact prompt — present in earlier checkpoints but removed from the latest snapshot — doesn't surface in rewind candidates.

## Deep Agent assumptions

The TUI expects the connected LangGraph server to:

- Expose at least one assistant via `assistants.search()`
- Accept `{"messages": [{"role": "user", "content": ...}]}` as run input
- Stream `updates` and `messages` chunks; subgraph streaming is required for subagent progress
- Express HITL interrupts via `HumanInTheLoopMiddleware` (preferred) or any dict with `question`/`description`/`options`
- Optionally populate `skills_metadata` in thread state for `SkillsMiddleware` skills

Anything else is treated as best-effort. The TUI never assumes the agent uses a specific tool set — tool widgets dispatch on tool name with aliasing (see [tool-widgets.md](tool-widgets.md)).
