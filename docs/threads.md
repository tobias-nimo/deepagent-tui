# Threads

How conversations are persisted, resumed, forked, and copied.

## Storage

The TUI keeps a local SQLite index at `~/.deepagent-tui/threads.db` (created on first run). It mirrors enough metadata to power the picker without re-querying the server.

```sql
CREATE TABLE threads (
    id            TEXT PRIMARY KEY,   -- the LangGraph thread_id
    graph_id      TEXT NOT NULL,      -- the graph/assistant the thread belongs to
    title         TEXT NOT NULL DEFAULT '',
    last_message  TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
)
```

Rows are written by `upsert_thread()` in three places:

1. On startup, when the session attaches to a thread (`bootstrap.connect`)
2. After each completed assistant turn — updates `last_message` (first 100 chars) and `message_count`
3. After `/new` and `/fork` — inserts the new thread

The actual conversation content (messages, checkpoints, tool calls) lives on the LangGraph server; this DB is only an index.

### Retention

The DB is capped at `MAX_THREADS = 20` rows (defined in `storage/db.py`). Every `upsert_thread` trims older rows past that limit by `updated_at DESC`, so the oldest threads fall off automatically as new ones come in. The cap only affects the local index — threads remain on the LangGraph server and can still be resumed by id with `/resume <thread_id>`.

## Resuming — `/resume`

### `/resume` with no argument

Opens a picker listing every **non-empty** thread in the local DB (up to the `MAX_THREADS` retention cap), filterable with type-to-search.

Each row shows:

- **Title** — the last message collapsed to a single line, truncated to 80 chars
- **Subtitle** — `<relative time>  ·  <graph>  ·  <N msgs>  ·  <id prefix>` (with `current  ·` prepended for the active thread)

### `/resume <thread_id>` or `/resume <prefix>`

Resolves in this order:

1. Exact id match in the local DB
2. Single prefix match in the local DB (ambiguous prefixes error out)
3. Server lookup as a fallback (in case the thread isn't in the local index yet)

### What happens on switch

`_switch_thread`:

1. Updates `session.thread_id` and resets local counters (messages, tokens, cost)
2. Fetches the thread state from the server
3. Calls `session.replay(messages)` — the TUI wipes the message log and renders past messages inline, so you return to the conversation in place rather than seeing a status banner

## Forking — `/fork`

Branches the current thread from an earlier user message into a new thread.

1. Fetches the thread's checkpoint history (`get_thread_history`)
2. Extracts every distinct user message
3. Opens a picker; the chosen message becomes the branch point
4. Creates a new thread pre-loaded with messages from the start up to (but not including) the **next** user message — i.e. the chosen user turn plus the assistant turn that responded to it (tool calls and results included)
5. Switches the session to the new thread and replays

Forking needs the original thread to have completed at least one run — the server requires an assigned `graph_id` on the source thread to copy state from. If it doesn't, the command reports `This thread has no history to fork from`.

## Copying — `/copy`

Writes the current thread's transcript to the system clipboard as plain markdown:

- User messages: `❯  <text>`
- Assistant messages: rendered as-is (markdown preserved)
- Tool calls and results are not included

Per-platform commands:

- macOS — `pbcopy`
- Windows — `clip`
- Linux/Wayland — `wl-copy`
- Linux/X11 — `xsel --clipboard --input`, falling back to `xclip -selection clipboard`

If none are available, the command reports the install hint.

## Implementation pointers

- `src/deepagent_tui/storage/db.py` — SQLite schema + helpers
- `src/deepagent_tui/commands/resume.py` — `/resume` and `_switch_thread`
- `src/deepagent_tui/commands/fork.py` — `/fork`
- `src/deepagent_tui/commands/copy.py` — `/copy`
- `src/deepagent_tui/commands/new.py` — `/new`
