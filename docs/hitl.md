# Human-in-the-loop approvals

How the TUI handles tool calls that pause the run for user approval.

## When the agent pauses

LangGraph's `HumanInTheLoopMiddleware` (and any other interrupt source) can pause a run before a tool executes. The TUI detects pending interrupts by polling `get_thread_state(thread_id)` after each turn settles and checking both `state["tasks"][*]["interrupts"]` and `state["interrupts"]`.

Two interrupt shapes are recognized:

1. **`HumanInTheLoopMiddleware` format** —
   ```json
   {
     "action_requests": [{"name": "edit_file", "args": {...}}],
     "review_configs": [{"action_name": "edit_file", "allowed_decisions": ["approve", "reject"]}]
   }
   ```
   Allowed decisions come from `review_configs[0].allowed_decisions`.

2. **Generic interrupt** — any dict with `question` / `description` / `message` / `action` / `type` keys, optionally with an `options` list. Falls back to `["approve", "reject"]` if no options are provided.

## The approval widget

When an interrupt is detected, the chat bar is hidden and an inline approval widget mounts at the bottom of the transcript. The widget shows:

- A bold title — for `edit_file`: `Do you want to make this edit to <basename>?`; otherwise `Do you want to proceed with <description>?`
- A numbered list of friendly options (`Yes` for approve/accept/yes, `No` for reject/deny/no, others titlecased)
- A hint line: `Esc to cancel · ↑/↓ to navigate · Enter to confirm`

The pending tool call widget is already visible above with a diff or argument summary (see [tool-widgets.md](tool-widgets.md)), so the approval prompt itself doesn't repeat the payload.

### Hidden options

The `edit` option is filtered out before display. Picking it would silently degrade to approve because the TUI doesn't currently round-trip through `$EDITOR` to collect the revised payload. Dropping it from the list avoids that surprise.

## Keyboard

| Key | Action |
|-----|--------|
| `1`–`9` | Select option N and confirm immediately |
| `↑` `↓` `Tab` `Shift+Tab` `Ctrl+P` `Ctrl+N` | Move the highlight |
| `Enter` | Confirm the highlighted option |
| `Esc` / `Ctrl+C` | Cancel — treated as `reject` |

## After a decision

The decision is converted into a `Command(resume=...)` payload:

- **Approve** → one `{"type": "approve"}` per action request
- **Reject** → one `{"type": "reject"}` per action request
- For non-HITL-middleware interrupts, the raw decision string is sent verbatim

The run resumes streaming. After it settles, thread state is polled again — **the loop keeps polling until no pending interrupts remain**. This matters because the agent often reacts to a rejection by trying a different tool call, which surfaces as a fresh interrupt during the resume stream. Bailing on the first reject would leave the next call paused server-side with no UI to approve it.

## Implementation pointers

- `src/deepagent_tui/handlers/interrupt.py` — extraction and resume-value construction
- `src/deepagent_tui/tui/inline_approval.py` — the widget itself
- `tui/app.py:_handle_interrupts` — the polling loop
- `tui/app.py:_inline_approve` — mounting / focus / cleanup
