# Configuration

`deepagent-tui` reads its settings from environment variables, with optional `.env` overrides. All settings are loaded via `pydantic-settings` (see `src/deepagent_tui/config.py`) and ignore unknown keys, so you can keep other variables in your `.env` without conflicts.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGGRAPH_URL` | `http://localhost:2024` | LangGraph server URL the TUI connects to on startup |
| `GRAPH_ID` | — (auto-discover) | Pin to a specific graph/assistant when the server exposes more than one |
| `THREAD_ID` | — | Resume a specific thread on startup instead of creating a new one |
| `LANGSMITH_API_KEY` | — | API key for authenticated connections (LangGraph Cloud) |

The theme is chosen with `/theme` in the TUI and persisted to `config.toml`; see [themes.md](themes.md) for the catalog. The workspace path shown in the hint bar and the `/export` banner is read from server thread state — the server is the authority.

## Command-line flags

The TUI accepts flags that override the matching env vars for a single launch. The same `--url`/`--graph`/`--thread` flags work across the headless subcommands (`deepagent query`/`resume`), so the vocabulary is identical everywhere:

| Flag | Overrides | Description |
|------|-----------|-------------|
| `--url URL` | `LANGGRAPH_URL` | LangGraph server URL to connect to |
| `--graph GRAPH_ID` | `GRAPH_ID` | Pin to a specific graph/assistant |
| `--thread THREAD_ID` | `THREAD_ID` | Attach to a specific thread on startup |

```bash
uv run deepagent tui --url http://localhost:2025 --graph my_agent
```

Bare `uv run deepagent` launches the TUI using only env/`.env`; pass flags via the explicit `deepagent tui` form.

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
| `~/.deepagent-tui/threads.db` | SQLite thread index (powers `/resume`); the picker is scoped per agent (`graph_id`) + workspace |
| `~/.deepagent-tui/config.toml` | Persisted preferences: theme, auto-approve (HITL), tool-widget mode, markdown on/off, thinking animation, language |
| `.env` | Per-directory configuration overrides |

A legacy `~/.deepagent-tui/theme` file from older versions is migrated into `config.toml` automatically on first launch, then removed.

### Per-agent scoping

Preferences and history don't bleed across agents:

- **Settings** — `config.toml` has a top-level **default** layer plus per-agent `[graph."<graph_id>"]` override tables. `/settings` (and `/theme`) write to the connected agent's section; an agent you've never customized inherits the defaults. A pre-scoping flat file is read unchanged as the default layer, so no migration is required.
- **History** — `/resume` lists only threads for the connected agent, narrowed further to the current workspace once the server reports one (before the first message it falls back to agent-only). Resolving a thread by explicit id/prefix is **not** scoped.

## Theme precedence

When the TUI starts, the theme is chosen in this order:

1. `theme` in the connected agent's `[graph."<graph_id>"]` section of `config.toml`, if present and valid (applied once `connect()` resolves the agent)
2. `theme` in the top-level default layer of `config.toml`, if present and valid
3. `default`

So once you've set a theme with `/theme <name>` while connected to an agent, that choice sticks for that agent across restarts.
