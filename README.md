# deepagent-tui

A terminal UI for any [LangChain Deep Agent](https://github.com/langchain-ai/deepagents) server. Connects to a LangGraph server over the SDK, streams replies as live markdown, surfaces tool calls inline, handles human-in-the-loop approvals with a diff view, and remembers threads locally so you can resume past sessions.

Built on [Textual](https://textual.textualize.io/).

<!-- TODO: replace with a short demo clip (asciinema .gif or .mp4) -->
<p align="center">
  <img src="assets/demo.gif" alt="deepagent-tui demo" width="720">
</p>

## Quick start

```bash
# Install
uv sync

# Start your Deep Agent server in another terminal
cd /path/to/your/agent && uv run langgraph dev --no-browser

# Launch the TUI
uv run deepagent-tui
```

The TUI connects to `LANGGRAPH_URL` (default `http://localhost:2024`), discovers an assistant, opens a fresh thread, and drops you at a prompt.

## Documentation

Full guides live in [`docs/`](docs/README.md):

- [Configuration](docs/configuration.md) · [Commands](docs/commands.md) · [HITL approvals](docs/hitl.md)
- [Threads](docs/threads.md) · [Skills](docs/skills.md) · [Architecture](docs/architecture.md)

## Configuration

Set via environment variables or a `.env` file in the working directory.

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGGRAPH_URL` | `http://localhost:2024` | LangGraph server URL |
| `GRAPH_ID` | auto-discover | Pin to a specific graph/assistant when the server exposes more than one |
| `LANGSMITH_API_KEY` | — | API key for authenticated connections |
| `THREAD_ID` | — | Resume a specific thread on startup |
| `DEEPAGENT_THEME` | `default` | UI theme: `default`, `aesthetic`, `vintage`, `monochrome`, `terminal`, `sunset`, `ocean`, `neon` |

See `example.env` for a copy-pasteable starting point.

## Slash commands

All commands start with `/` and have tab-completion (the autocomplete list appears as you type).

| Command | Description |
|---------|-------------|
| `/help` | List all available commands |
| `/status` | Show connection info, model, token usage, cost |
| `/new` | Start a fresh conversation thread |
| `/clear` | Wipe the message log |
| `/exit` | Quit the TUI |
| `/threads` | List saved conversation threads |
| `/resume [thread_id]` | Open the thread picker, or jump straight to a thread by id |
| `/fork` | Browse the current thread's history and branch from a past user message |
| `/export` | Save the conversation as a markdown transcript under `.workspace/history/` |
| `/copy` | Copy the conversation to the clipboard |
| `/theme [name]` | Switch UI theme; no argument lists themes with previews |
| `/skills` | List skills discovered from the connected agent |
| `/skills refresh` | Re-fetch skills from the current thread's state |
| `/<skill-name> [question]` | Invoke a discovered skill — the agent reads its `SKILL.md` and acts |

## Key bindings

| Key | Action |
|-----|--------|
| `Enter` | Submit the message |
| `Shift+Enter` / `Alt+Enter` / `Ctrl+J` | Insert a newline |
| `Tab` | Complete the highlighted slash command |
| `↑` / `↓` | Move the cursor; at the top/bottom of the input, scroll the transcript |
| `PgUp` / `PgDn` | Scroll the transcript by a page |
| `Esc` | Close autocomplete · clear pending attachments · cancel the in-flight stream and put your message back in the input |
| `Ctrl+L` | Clear the message log |
| `Ctrl+C` | Quit |

`Shift+Enter` depends on your terminal forwarding the modifier — Kitty, Ghostty, WezTerm, and iTerm2 (with "Report modifiers using CSI u" enabled) do; some don't. `Alt+Enter` and `Ctrl+J` always work.

## Human-in-the-loop approvals

When the agent calls a tool that's gated for approval (e.g. `edit_file`), the run pauses on the server and the TUI shows the pending call inline with a diff or argument summary. Choose `approve` / `reject` (number key or `↑`/`↓` + `Enter`); `Esc` rejects. After a reject, the agent typically retries with a different approach, and the next interrupt is handled by the same flow until the turn settles.

## Images

Paste an image path (or drop a file into a terminal that yields a path) and it's attached to the next message. Multiple images stack; `Esc` clears pending attachments.

## File locations

| Path | Purpose |
|------|---------|
| `~/.deepagent-tui/threads.db` | Local thread index (SQLite). Powers `/threads` and `/resume` |
| `~/.deepagent-tui/theme` | Persisted theme name set by `/theme` |
| `.env` | Configuration overrides for the working directory |
| `.workspace/history/<thread_id>.md` | Markdown transcripts written by `/export` (in the current working directory) |

## Development

```bash
# Run smoke tests (no server required — bootstrap is stubbed)
uv run pytest

# Lint
uv run ruff check
```

The smoke tests in `tests/test_tui_smoke.py` boot the app with a fake connect/discover and assert the layout mounts and basic interactions don't blow up. They run in ~0.5s and are the first thing to break if a refactor disturbs the wiring.
