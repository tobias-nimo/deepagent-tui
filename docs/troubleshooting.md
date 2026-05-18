# Troubleshooting

Common failure modes and how to recover.

## TUI can't connect to the server

> Symptoms, things to check (`LANGGRAPH_URL`, server up, network), how to read the error.

## Wrong assistant / multiple graphs

> When auto-discovery picks the wrong one — pin with `GRAPH_ID`.

## Auth failures

> When `LANGSMITH_API_KEY` is required, how to confirm it's loaded.

## `Shift+Enter` inserts garbage instead of a newline

> Terminal doesn't forward the modifier. Use `Alt+Enter` or `Ctrl+J`; see [keybindings.md](keybindings.md) for the terminal compatibility list.

## Image paste doesn't attach

> When the terminal doesn't yield a path, what to do, recognized formats.

## Thread doesn't appear in `/threads`

> When the local SQLite index drifts from server state, how to recover or reset (`~/.deepagent-tui/threads.db`).

## Theme reverts on restart

> Persistence file location, env override precedence.

## Approval prompt seems stuck

> What to check server-side, how `Esc` interacts with retries. See [hitl.md](hitl.md).
