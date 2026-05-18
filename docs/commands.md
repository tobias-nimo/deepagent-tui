# Commands

All commands start with `/` and have tab-completion. While typing a slash command, an autocomplete list shows matches with their descriptions. **Built-in commands take precedence over dynamic skill commands** with the same name.

## Session

### `/help`
Lists built-in commands as a table with names and descriptions. (Dynamic skill commands appear via `/skills` instead.)

### `/status`
Shows the current session at a glance:

- Server URL, graph id, assistant id, thread id
- Model name (populated once the first response streams in)
- Current status: `idle` / `streaming` / `interrupted`
- Cumulative input/output tokens and estimated cost

Cost is computed from a built-in pricing table for known models (see `utils/cost.py`); unknown models show `$0.0000`.

### `/new`
Wipes the message log, asks the server for a fresh thread, and resets the session counters (tokens, cost, local messages). The new thread is recorded in the local index.

### `/clear`
Clears the message log without creating a new thread. Equivalent to `Ctrl+L`.

### `/exit`
Quits the TUI. Equivalent to `Ctrl+C`.

## History

### `/resume [thread_id]`

- **No argument** — opens a picker showing up to the 10 most recent non-empty threads (filterable by typing). Selecting one switches the session to that thread, fetches its state from the server, and replays the conversation inline.
- **Full or partial id** — `/resume abc12` resolves to a thread whose id starts with `abc12`. Ambiguous prefixes are rejected with an error. If the id isn't in the local DB, the server is queried directly as a fallback.

Switching threads resets token/cost counters and re-renders past messages in place (no banner).

### `/fork`
Opens a picker of up to the last 10 distinct user messages from the current thread's history. Selecting one creates a new thread pre-loaded with messages up to (but not including) the next user message — i.e. the chosen user turn and the assistant turn that responded to it. The session switches to the new thread and replays.

Forking requires the original thread to have at least one completed run (the server needs an assigned `graph_id` to copy state from).

### `/copy`
Copies the conversation as markdown to the system clipboard. User messages are prefixed with `❯`, assistant messages are rendered as-is. Uses `pbcopy` on macOS, `clip` on Windows, and tries `wl-copy` → `xsel` → `xclip` on Linux. Missing tools produce a helpful error.

## Appearance

### `/theme [name]`

- **No argument** — prints the current theme and a table of every theme with gradient/accent/command color swatches.
- **`/theme <name>`** — switches the theme and writes the choice to `~/.deepagent-tui/theme` so it persists across restarts.

The welcome banner repaints after any command, so theme changes take effect immediately.

## Skills

Skills are reusable agent capabilities exposed by the connected server. See [skills.md](skills.md) for the discovery rules.

### `/skills`
Lists the currently-registered skill commands as a table.

### `/skills refresh`
Re-fetches `skills_metadata` from the current thread's state and registers any skills found. Useful when the agent loads skills lazily (the first message often triggers the load, after which `/skills refresh` will surface them).

### `/<skill-name> [question]`
Invokes a registered skill. The TUI sends `Use the <name> skill` to the agent (with `: <question>` appended if you pass an argument) and streams the response. The agent reads the skill's `SKILL.md` and decides how to act.

## How dispatch works

`src/deepagent_tui/commands/__init__.py` maintains two registries:

- **Built-in** — populated at import time via the `@command(name, description)` decorator.
- **Dynamic** — populated at runtime by `register_skill()` during discovery; cleared on reconnect.

Lookup checks built-in first, then dynamic. Unknown slash commands surface a `Unknown command:` line — they are **not** forwarded to the agent as free text.

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

Output should go through `render_info` / `render_error` (from `ui/renderer.py`) — the TUI captures the rich console and replays the output inline.
