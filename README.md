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

- **Using it** — [Configuration](docs/configuration.md) · [Commands](docs/commands.md) · [Key bindings](docs/keybindings.md) · [Themes](docs/themes.md) · [Images](docs/images.md) · [HITL approvals](docs/hitl.md) · [Threads](docs/threads.md) · [Skills](docs/skills.md) · [Troubleshooting](docs/troubleshooting.md)
- **Hacking on it** — [Architecture](docs/architecture.md) · [Tool widgets](docs/tool-widgets.md) · [Testing](docs/testing.md)

## Development

```bash
# Run smoke tests (no server required — bootstrap is stubbed)
uv run pytest

# Lint
uv run ruff check
```

The smoke tests in `tests/test_tui_smoke.py` boot the app with a fake connect/discover and assert the layout mounts and basic interactions don't blow up. They run in ~0.5s and are the first thing to break if a refactor disturbs the wiring.
