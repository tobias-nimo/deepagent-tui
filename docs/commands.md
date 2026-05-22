# Commands

All commands start with `/` and have tab-completion. While typing a slash command, an autocomplete list shows matches with their descriptions. **Built-in commands take precedence over dynamic skill commands** with the same name.

## Session

### `/commands`
Opens a full-screen list of built-in commands (`CommandsScreen` in `tui/screens.py`). The screen ends with a short note explaining that skills are invoked as `/<skill-name>` and pointing to `/skills` to see what the current agent exposes. Esc / Ctrl+C / q closes it; up/down/PageUp/PageDown scroll.

### `/help`
Opens a full-screen help view (`HelpScreen` in `tui/screens.py`) with keyboard shortcuts and tips. Esc / Ctrl+C / q closes it; up/down/PageUp/PageDown scroll. Same modal-screen pattern as `/commands`, `/resume`, and `/fork`.

### `/status`
Opens a full-screen view (`StatusScreen` in `tui/screens.py`) of the current session, split into two sections:

- **Connection** — server URL, graph id, assistant id, thread id, model name (populated once the first response streams in), current status (`idle` / `streaming` / `interrupted`).
- **Usage** — cumulative input/output tokens and estimated cost.

Esc / Ctrl+C / q closes it; up/down/PageUp/PageDown scroll. Cost is computed from a built-in pricing table for known models (see `utils/cost.py`); unknown models show `$0.0000`.

### `/new`
Clears the previous conversation, asks the server for a fresh thread, and resets the session counters (tokens, cost, local messages). The transcript keeps just the `❯ /new` submission and a `⎿ New thread: <id>` acknowledgment so there's a visible trace of what happened.

### `/clear`
Clears the message log without creating a new thread. Equivalent to `Ctrl+L`.

### `/exit`
Quits the TUI. Equivalent to `Ctrl+C`.

## History

### `/resume [thread_id]`

- **No argument** — opens a picker listing every non-empty thread in the local DB (capped at `MAX_THREADS = 20`, filterable by typing). Selecting one switches the session to that thread, fetches its state from the server, and replays the conversation inline.
- **Full or partial id** — `/resume abc12` resolves to a thread whose id starts with `abc12`. Ambiguous prefixes are rejected with an error. If the id isn't in the local DB, the server is queried directly as a fallback.

Switching threads resets token/cost counters and re-renders past messages in place, with a `⎿ Resumed thread: <id>` line above the replayed conversation.

### `/fork`
Opens a picker of every distinct user message from the current thread's history. Selecting one creates a new thread pre-loaded with messages up to (but not including) the chosen user message — restoring the conversation to the point right before that turn. The session switches to the new thread, replays under a `⎿ Forked <new_id> from message #m.` header, and pre-fills the chat bar with the chosen message so it can be edited and resent. Dismissing the picker prints `⎿ Cancelled.`

Forking requires the original thread to have at least one completed run (the server needs an assigned `graph_id` to copy state from).

### `/copy`
Copies the **last assistant turn** (final response plus any tool calls/results from that turn) to the system clipboard. Use `/export` for the full conversation.

### `/export`
Copies the **entire conversation** to the system clipboard. User messages are prefixed with `❯`, assistant text is rendered as-is.

Both commands format tool activity as fenced blocks, pairing each call with its result by `tool_call_id`:

````
```
tool_name(arg=value, ...)
⎿ result text
```
````

A call with no matching result yet (pending or interrupted) is emitted without the `⎿` line. Clipboard backend: `pbcopy` on macOS, `clip` on Windows, `wl-copy` → `xsel` → `xclip` on Linux. Missing tools produce a helpful error.

## Appearance

### `/theme [name]`

- **No argument** — opens a picker (`PickerScreen`) listing every theme; each row shows an interpolated gradient bar plus accent/command color swatches, with the active theme tagged `current`. Selecting one applies + persists it (`⎿ Theme set to: <name>`); dismissing prints `⎿ Cancelled.`
- **`/theme <name>`** — switches the theme directly and writes the choice to `~/.deepagent-tui/theme` so it persists across restarts.

The welcome banner repaints after any command, so theme changes take effect immediately.

## Skills

Skills are reusable agent capabilities exposed by the connected server. See [skills.md](skills.md) for the discovery rules.

### `/skills`
Opens a full-screen picker of the currently-registered skills (filterable by typing — matches both name and description). Selecting one prints `⎿ /skill-name` and pre-fills the chat input with `/<skill-name> ` so you can add arguments and submit. Dismissing prints `⎿ Cancelled.`

### `/skills refresh`
Re-fetches `skills_metadata` from the current thread's state and registers any skills found. Useful when the agent loads skills lazily (the first message often triggers the load, after which `/skills refresh` will surface them).

### `/<skill-name> [question]`
Invokes a registered skill. The TUI sends `Use the <name> skill` to the agent (with `: <question>` appended if you pass an argument) and streams the response. The agent reads the skill's `SKILL.md` and decides how to act.

## How dispatch works

`src/deepagent_tui/commands/__init__.py` maintains two registries:

- **Built-in** — populated at import time via the `@command(name, description)` decorator.
- **Dynamic** — populated at runtime by `register_skill()` during discovery; cleared on reconnect.

Lookup checks built-in first, then dynamic. Unknown slash commands surface a red `⎿ Unknown command` line — they are **not** forwarded to the agent as free text.

`/clear` and dynamic skill commands take TUI-specific paths (see `tui/app.py:_run_command`) rather than running the registered handler, because the registered handlers were originally written for the now-removed REPL frontend.

## Adding a new command

Drop a module in `src/deepagent_tui/commands/`, define a handler, and decorate it:

```python
from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import render_info

@command("ping", "Reply with pong")
async def cmd_ping(client, session, args: str) -> None:
    render_info("pong")
```

Then add the module to the side-effect import block at the bottom of `commands/__init__.py` so the decorator fires on startup.

Output should go through `render_info` / `render_error` (from `ui/renderer.py`). Each call renders as a single Textual widget under a dim `⎿` corner — `render_info` paints the body dim, `render_error` paints it red. Multi-line strings share one `⎿` with subsequent lines aligned under the first. To inline an arbitrary Rich renderable (e.g. a `Table`), use `render_renderable`. Full-screen modal hooks (`/help`, `/commands`, `/status`) call `render_info("<Name> dialog dismissed.")` after `push_screen_wait` returns. The mount sink is installed by `tui/app.py` on startup; in CLI mode (no sink) the same calls fall through to the shared rich console.
