# Configuration

`deepagent-tui` reads its settings from environment variables, with optional `.env` overrides. All settings are loaded via `pydantic-settings` (see `src/deepagent_tui/config.py`) and ignore unknown keys, so you can keep other variables in your `.env` without conflicts.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGGRAPH_URL` | `http://localhost:2024` | LangGraph server URL the TUI connects to on startup |
| `GRAPH_ID` | — (auto-discover) | Pin to a specific graph/assistant when the server exposes more than one |
| `THREAD_ID` | — | Resume a specific thread on startup instead of creating a new one |
| `LANGSMITH_API_KEY` | — | API key for authenticated connections (LangGraph Cloud) |
| `DEEPAGENT_THEME` | `default` | Initial UI theme |
| `DEEPAGENT_WORKSPACE` | — | Workspace path shown in the hint bar (rotates with tips while idle) and in the `/export` banner. Overrides whatever the server reports. |

`DEEPAGENT_THEME` must be one of: `default`, `aesthetic`, `vintage`, `monochrome`, `terminal`, `sunset`, `ocean`, `neon`, `langchain`. See [themes.md](themes.md) for the catalog.

`DEEPAGENT_WORKSPACE` is a display-only override. If unset, the TUI reads the workspace from thread state — the server is the authority. Set this when the server doesn't expose a workspace key, or when you want a different label (e.g. a symlink target, a short alias).

## `.env` files

A `.env` file in the current working directory is loaded automatically. See `example.env` at the repo root for a copy-pasteable starting point. The TUI doesn't search parent directories — `.env` must sit in the directory you launch it from.

Variables already set in the shell environment take precedence over `.env`.

## Discovery behavior

On startup, the TUI calls `discover_assistants()` against `LANGGRAPH_URL`:

- **No `GRAPH_ID` set + one assistant on the server** → uses it.
- **No `GRAPH_ID` set + multiple assistants** → uses the **first one** and prints the list with a hint to set `GRAPH_ID`. There is no interactive picker for this case.
- **`GRAPH_ID` set + matches an assistant** → uses it.
- **`GRAPH_ID` set + no match** → prints the available graphs and exits.

If `THREAD_ID` is set, the TUI attaches to that thread (the server is not asked to create a new one). Otherwise a fresh thread is created and recorded in the local index.

## File locations

| Path | Purpose |
|------|---------|
| `~/.deepagent-tui/threads.db` | SQLite thread index (powers `/resume`) |
| `~/.deepagent-tui/theme` | Persisted theme name written by `/theme` |
| `.env` | Per-directory configuration overrides |

## Theme precedence

When the TUI starts, the theme is chosen in this order:

1. `~/.deepagent-tui/theme` if present and valid
2. `DEEPAGENT_THEME` env var if set and valid
3. `default`

So once you've set a theme with `/theme <name>`, that choice sticks across restarts regardless of what `DEEPAGENT_THEME` is set to.
