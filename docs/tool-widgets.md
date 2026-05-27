# Tool widgets

Built-in tools get custom inline widgets so calls render meaningfully instead of as a JSON blob. Each tool name maps to a renderer that knows how to format its arguments and result.

## Anatomy of a widget

Every tool widget has two states that share the same `.msg` block (so call and result don't get separated by a margin row):

```
○ Edit  src/foo.py            ← pending: name + summary
   ⎿ Added 3 lines, removed 1 line
     - old line
     + new line
     + another new line
     + and another
```

When the result arrives, the pending widget is rebuilt with:

- The marker flipped from `○` (pending, dim) to one of `●` (success, green), `●` (error, red), or `●` (rejected, amber)
- The result body (`⎿ ...`) appended

For Edit and Write, the diff/added-lines preview is shown in the **pending** state so the user can review before approving. Once the result arrives, the call widget shrinks back to just the header and the result widget takes over the diff so it doesn't render twice.

## Recognized tools

Dispatch normalizes tool names through `_tool_alias` so different conventions land on the same renderer:

| Alias | Source names | Widget |
|-------|--------------|--------|
| `edit` | `edit_file`, `str_replace_editor` | **Edit** — diff body with `+`/`-` lines on tinted backgrounds, capped at 7 lines |
| `write` | `write_file`, `create_file` | **Write** — full content as a single `+` block, capped at 7 lines |
| `read` | `read_file`, `open_file` | **Read** — `path  (offset=N, limit=M)`; result is `⎿ N lines` |
| `grep` | `grep` | **Search** — `"pattern"  in <path>  (<glob>)`; result is `⎿ N matches` |
| `glob` | `glob` | **Find** — `<pattern>  in <path>`; result is `⎿ N matches` |
| `bash` | `bash`, `shell`, `run_shell`, `run_command`, `execute` | **Bash** — command + description; result is the truncated stdout/stderr |
| `ls` | `ls`, `list_files`, `list_directory` | **List** — path; result is up to 5 entries + `… (+N more)` |
| `write_todos` | `write_todos`, `todo_write`, `todowrite` | **Todos** — `2/4 · 1 in progress`, with each todo as `● done`, `◐ active`, `○ pending`, `— skipped` |
| `task` (subagent) | `task`, `delegate`, `create_task`, `spawn_agent` | **Subagent** — `subagent_type`, plus rolling `⎿` progress lines for inner tool calls; result body suppressed (parent re-summarizes) |
| (anything else) | — | **Generic** — name + truncated args; result is the truncated content |

## Sticky plan card

When the agent calls `write_todos`, a **PlanCard** is also pinned above the chat bar showing the same todo list. It stays there across turns until every todo is `completed` or `skipped/cancelled` — then it auto-hides. `/clear`, `/new`, and `/resume` also clear it. While the card is visible, the inline `write_todos` widget in the scroll log is collapsed (`.-plan-suppressed`) so the plan doesn't double-render. The card is hidden alongside the chat bar during HITL approval prompts. See `PlanCard` in `tui/app.py` and `render_todos_widget` / `todos_all_completed` in `ui/tool_widgets.py`.

## Result suppression

Two tools opt out of rendering their result body:

- **`task` (subagent)** — the parent agent re-summarizes the subagent's output in its next turn, so re-printing the raw return value is redundant. The `⎿` progress lines on the call widget already show what the subagent did.
- **`write_todos`** — the call widget above already shows the post-update list with status glyphs, so the `Updated todo list to [...]` return value would be noise. Errors are still surfaced.

## HITL rejection

When the user rejects a HITL approval, the LangChain `HumanInTheLoopMiddleware` writes a `ToolMessage` with `status="error"` and content like `User rejected the tool call ...`. The TUI sniffs that prefix (`_HITL_REJECT_PREFIX`) and renders `⎿ Rejected by user` with the amber `●` marker instead of treating it as a tool error.

## Subagent progress

When a tool call has `name in SUBAGENT_TOOL_NAMES`, the widget is rendered as a Subagent. As inner activity streams in over `updates|<namespace>` events, `_handle_subagent_update` appends `(tool_name, summary)` lines to a per-task list. The widget shows a rolling window of the most recent 3 entries:

```
○ Subagent  general-purpose
   ⎿ Bash  ls -la src/
   ⎿ Read  src/app.py
   ⎿ Edit  src/app.py
```

When the subagent returns, the marker flips to its final state and the result body is suppressed.

## Diff rendering

Edit and Write use these colors so diffs land legibly on both truecolor and 256-color terminals:

| | Background | Foreground |
|---|------------|------------|
| Added | `#0e2718` (deep green) | `#2ea043` (bright green) |
| Removed | `#2c1414` (deep red) | `#f85149` (bright red) |

Long diffs are capped at 7 lines with `… (+N more line(s))`.

## Adding a widget

1. Add a renderer for the call:
   ```python
   def _call_my_tool(tc: FormattedToolCall, state: str) -> RenderableType:
       summary = Text(str(tc.args.get("target", "")), style="dim")
       return _header("MyTool", summary, state=state)
   ```
2. Add a renderer for the result (return `None` to suppress):
   ```python
   def _result_my_tool(result: FormattedToolResult, call) -> RenderableType:
       if result.is_error:
           return _result_inline(result.summary, error=True)
       return _corner_inline("done")
   ```
3. Register both:
   ```python
   _CALL_RENDERERS["my_tool"] = _call_my_tool
   _RESULT_RENDERERS["my_tool"] = _result_my_tool
   ```
4. Add aliases to `_tool_alias` if the agent might use different names.

## Implementation pointers

- `src/deepagent_tui/ui/tool_widgets.py` — all renderers
- `src/deepagent_tui/handlers/tools.py` — `format_tool_call` / `format_tool_result`
- `src/deepagent_tui/tui/app.py:_write_tool_call`, `_write_tool_result`, `_handle_subagent_update` — mounting and update flow
