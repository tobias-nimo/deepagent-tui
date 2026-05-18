# Configuration

How `deepagent-tui` reads its settings, what each knob does, and where state lives on disk.

## Environment variables

> Cover each variable: default, accepted values, when you'd change it, interactions with other vars.

- `LANGGRAPH_URL`
- `GRAPH_ID`
- `LANGSMITH_API_KEY`
- `THREAD_ID`
- `DEEPAGENT_THEME`

## `.env` files

> Loading order, working-directory resolution, relationship to `example.env`.

## File locations

> What's written where, and what's safe to delete.

- `~/.deepagent-tui/threads.db` — local thread index (SQLite)
- `~/.deepagent-tui/theme` — persisted theme
- `.workspace/history/<thread_id>.md` — markdown transcripts from `/export`

## Themes

> Quick pointer; full catalog lives in `themes.md` (planned).
