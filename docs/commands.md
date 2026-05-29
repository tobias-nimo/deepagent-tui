# Commands

All commands start with `/` and have tab-completion. While typing a slash command, an autocomplete list shows matches with their descriptions. **Built-in commands take precedence over dynamic skill commands** with the same name.

## Session

### `/help`
Opens a four-tab modal docked to the bottom 60% of the screen (`HelpScreen` in `tui/screens.py`). `Shift+Tab` / `Tab` (also `[` / `]`) cycles tabs; `Esc` / `Ctrl+C` / `q` closes.

- **Help** — friendly welcome plus a short overview of the TUI and deep agents, followed by getting-started instructions.
- **Keyboard** — keyboard shortcuts (Enter / Shift+Enter / Tab / Esc / ↑↓ message recall / Shift+arrows selection / Shift+Tab focus toggle / Fn+↑↓ paging).
- **Tips** — quick workflow hints (slash commands, @ file references, ! shell commands, passing images, skills, /resume, /rewind, /theme).
- **Commands** — the full list of built-in slash commands (name + description), followed by a short note explaining that skills are invoked as `/<skill-name>` and pointing to `/skills` to see what the current agent exposes.

### `/new`
Clears the previous conversation, asks the server for a fresh thread, and resets the session counters (tokens, cost, local messages). The transcript keeps just the `❯ /new` submission and a `⎿ New thread: <id>` acknowledgment so there's a visible trace of what happened.

### `/clear`
Clears the message log without creating a new thread. Equivalent to `Ctrl+L`.

### `/exit`
Quits the TUI. Equivalent to `Ctrl+C`.

## History

### `/resume [thread_id]`

- **No argument** — opens a picker listing the non-empty threads in the local DB (capped at `MAX_THREADS = 20`, filterable by typing), **scoped to the connected agent** (`graph_id`) and, once the server reports one, the current workspace. Selecting one switches the session to that thread, fetches its state from the server, and replays the conversation inline.
- **Full or partial id** — `/resume abc12` resolves to a thread whose id starts with `abc12`. This lookup is **not** scoped, so you can attach to threads from any agent/workspace. Ambiguous prefixes are rejected with an error. If the id isn't in the local DB, the server is queried directly as a fallback.

Switching threads resets token/cost counters and re-renders past messages in place, with a `⎿ Resumed thread: <id>` line above the replayed conversation.

### `/rewind`
Opens a picker of every distinct user message from the current thread's history. Selecting one creates a new thread pre-loaded with messages up to (but not including) the chosen user message — restoring the conversation to the point right before that turn. The session switches to the new thread, replays under a `⎿ Rewound to message #m (new thread <new_id>).` header, and pre-fills the chat bar with the chosen message so it can be edited and resent. Dismissing the picker prints `⎿ Cancelled.`

Rewinding requires the original thread to have at least one completed run (the server needs an assigned `graph_id` to copy state from).

### `/compact`
Asks the agent to summarise older messages via its `compact_conversation` tool, freeing up context window space. Runs silently — a dim animated `⎿ Compacting…` placeholder is shown during the operation, then replaced by `⎿ Summarised N messages …` (success) or `⎿ Nothing to compact yet — conversation is within the token budget.` (when the agent's eligibility gate denies because the conversation is too small to be worth compacting).

Every message the operation added to thread state (the internal prompt, the AI tool call, the tool result, and the model's follow-up) is removed via `RemoveMessage` on completion — only the slash-style trace remains. On success, the actual summary lives in `_summarization_event` state and is applied to subsequent model runs by `SummarizationMiddleware`.

Requires `SummarizationToolMiddleware` on the agent server. Without it the command reports `Error executing compact_conversation tool.` See [server-middleware.md](server-middleware.md#conversation-compaction) for the wiring recipe.

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
- **`/theme <name>`** — switches the theme directly and writes the choice to `~/.deepagent-tui/config.toml` so it persists across restarts. Like all settings, it's scoped to the connected agent's `[graph."<graph_id>"]` section — see [configuration.md](configuration.md#per-agent-scoping).

The welcome banner repaints after any command, so theme changes take effect immediately.

### `/settings`
Opens a four-tab modal docked to the bottom 60% of the screen (the chat behind stays visible through a hazy backdrop). `Shift+Tab` / `Tab` (also `[` / `]`) cycles tabs; `Esc` / `Ctrl+C` / `q` closes.

- **Config** — six interactive rows; ↑↓ moves the highlight, ←→ (or `Space`) cycles the value. Changes apply live and are persisted to the connected agent's section of `~/.deepagent-tui/config.toml`, so they don't affect other agents (see [configuration.md](configuration.md#per-agent-scoping)).
  - `Tool widgets output` — tool-widget verbosity: `compacted` (header only), `default` (capped preview), `expanded` (no per-tool cap; full diffs, full bash output, full Ls listings, full subagent progress). Changing this re-renders existing tool widgets in the transcript, not just future ones.
  - `Auto-approve tools` — `off` shows the inline approval widget on interrupts; `on` auto-accepts them.
  - `Markdown rendering` — `on` renders assistant text through Rich Markdown; `off` falls back to raw `Text` (useful for debugging streamed payloads). Changing this re-renders existing assistant messages in the transcript, not just future ones.
  - `Thinking animation` — cycles the streaming "Thinking…" animation: `braille`, `pulse`, `shimmer`, `gradient`, `typewriter`, `sparkle` (`shimmer`/`gradient` follow the active theme).
  - `Language` — placeholder locked to `english` today.
  - `Theme` — cycles through the same themes available to `/theme`. Persisted to `~/.deepagent-tui/config.toml` like the other rows.
- **Harness** — static: `Model`, `Tools`, `Subagents`, `Skills`. `Tools` and `Subagents` come from `agent_info_middleware` and render `—` when it's not attached. See [server-middleware.md](server-middleware.md#agent-info-tools--subagents).
- **Usage** — static meters: `Context` (a `current / max  ████░░  N%` bar where `current` is the most recent single-call input-token count), `Tokens` (cumulative in/out), `Cost`. Context window and per-token prices come from `llm_info_middleware`; when missing, the rows render as `unknown (llm_info_middleware not attached …)`. A footnote under the table flags that cost covers the main agent only when subagents are registered. See [server-middleware.md](server-middleware.md#llm-info-context-window--pricing).
- **Status** — static: `Server`, `Graph`, `Assistant`, `Thread`, `Status`.

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

Output should go through `render_info` / `render_error` (from `ui/renderer.py`). Each call renders as a single Textual widget under a dim `⎿` corner — `render_info` paints the body dim, `render_error` paints it red. Multi-line strings share one `⎿` with subsequent lines aligned under the first. To inline an arbitrary Rich renderable (e.g. a `Table`), use `render_renderable`. Full-screen modal hooks (`/help`, `/settings`) call `render_info("<Name> dialog dismissed.")` after `push_screen_wait` returns. The mount sink is installed by `tui/app.py` on startup; in CLI mode (no sink) the same calls fall through to the shared rich console.
