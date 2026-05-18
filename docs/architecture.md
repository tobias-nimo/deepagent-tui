# Architecture

How the codebase is laid out and how a single turn flows through it.

## Package map

```
src/deepagent_tui/
├── bootstrap.py     # Startup: load config, connect, discover assistant, open thread
├── config.py        # Env + .env loading
├── client.py        # LangGraph SDK wrapper
├── session.py       # Per-thread state and helpers
├── tui/             # Textual app, screens, inline approval widget
├── ui/              # Renderers (markdown, tool widgets, themes)
├── commands/        # Slash command implementations
├── handlers/        # Stream / interrupt / tool-call handling
├── storage/         # SQLite thread index
└── utils/           # Tokens, cost, image helpers
```

## A turn, end to end

> Walk through: user submits → `tui/app.py` sends to `client.py` → server streams events → `handlers/stream.py` dispatches to `handlers/tools.py` and `handlers/interrupt.py` → `ui/renderer.py` paints → final assistant message lands → `storage/db.py` updates the thread row.

## Key seams

> Where to plug in a new command, a new tool widget, a new theme, a new storage backend.

## Deep Agent assumptions

> What the TUI expects from the connected LangGraph server (state shape, interrupt format, tool metadata). See [`deepagent.md`](deepagent.md) (planned) for background on Deep Agents themselves.

## Testing

> Smoke tests in `tests/test_tui_smoke.py` stub bootstrap and assert the app mounts. See `testing.md` (planned) for the full pattern.
