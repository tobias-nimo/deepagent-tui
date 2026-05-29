# Threads

How conversations are persisted, resumed, rewound, and copied.

## Storage

The TUI keeps a local SQLite index at `~/.deepagent-tui/threads.db` (created on first run). It mirrors enough metadata to power the picker without re-querying the server.

```sql
CREATE TABLE threads (
    id            TEXT PRIMARY KEY,   -- the LangGraph thread_id
    graph_id      TEXT NOT NULL,      -- the graph/assistant the thread belongs to
    workspace     TEXT,               -- the agent's workspace root, when reported
    title         TEXT NOT NULL DEFAULT '',
    last_message  TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
)
```

Rows are written by `upsert_thread()` only after a completed assistant turn — it sets `last_message` (first 100 chars) and `message_count`. Threads with no messages aren't indexed locally: bootstrap, `/new`, and `/rewind` create the server thread but defer the row until the first turn lands, so abandoned launches/rewinds don't evict real conversations under the retention cap.

`workspace` is the agent's workspace root (`session.workspace_root`), which often isn't known until the server reports it after the first message. It's written only when known, so a later turn backfills it without an earlier `NULL` clobbering the value. Databases created before this column was added are migrated in place (`ALTER TABLE … ADD COLUMN`) on first open.

The actual conversation content (messages, checkpoints, tool calls) lives on the LangGraph server; this DB is only an index.

### Retention

The DB is capped at `MAX_THREADS = 20` rows (defined in `storage/db.py`). Every `upsert_thread` trims older rows past that limit by `updated_at DESC`, so the oldest threads fall off automatically as new ones come in. The cap only affects the local index — threads remain on the LangGraph server and can still be resumed by id with `/resume <thread_id>`.

## Resuming — `/resume`

### `/resume` with no argument

Opens a picker listing the **non-empty** threads in the local DB (up to the `MAX_THREADS` retention cap), filterable with type-to-search. The list is **scoped to the connected agent** (`graph_id`), and further to the current `workspace` when the server has reported one — so threads from other agents/workspaces don't bleed into the picker. Before the workspace is known (no message sent yet in the session), the picker falls back to graph-only scoping rather than hiding threads it can't yet classify. Resolving a thread by explicit id/prefix (below) is **not** scoped, so you can still attach to any thread you know the id of.

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
3. Calls `session.replay(messages, header=f"Resumed thread: {thread_id}")` — the TUI preserves the `❯ /resume` submission, mounts the header as a `⎿ Resumed thread: <id>` line, then renders past messages inline so you return to the conversation in place

## Rewinding — `/rewind`

Branches the current thread from an earlier user message into a new thread.

1. Fetches the thread's checkpoint history (`get_thread_history`)
2. Extracts every distinct user message
3. Opens a picker; the chosen message becomes the branch point
4. Creates a new thread pre-loaded with messages from the start up to (but not including) the **chosen** user message — restoring the conversation to the point right before it
5. Switches the session to the new thread, replays under a `⎿ Rewound to message #m (new thread <new_id>).` header, and pre-fills the chat bar with the chosen message's text so it can be edited and resent

Rewinding needs the original thread to have completed at least one run — the server requires an assigned `graph_id` on the source thread to copy state from. If it doesn't, the command reports `This thread has no history to rewind to`.

### Filtering removed messages

LangGraph keeps every checkpoint, so a message deleted via `RemoveMessage` (e.g. the internal prompt that `/compact` issues, then cleans up) still lives in earlier snapshots. The rewind picker would otherwise surface those as rewind candidates. To avoid that, `/rewind` reads the latest thread state once, builds a set of live message IDs, and skips any checkpoint message whose id isn't in that set. The filter is generic — it applies to any user message that was later removed, not just to `/compact`.

## Copying — `/copy` and `/export`

Two clipboard commands, both targeting the system clipboard:

- **`/copy`** — the **last assistant turn** only: final response text plus any tool calls/results that occurred in that turn. Useful for grabbing one answer to paste elsewhere.
- **`/export`** — the **entire conversation**: every user turn (prefixed with `❯  `, with continuation lines indented by 3 spaces to align), every assistant response, and all tool activity. The output is preceded by the same ASCII welcome banner the TUI shows on launch (graph name + workspace path).

Tool calls are rendered as fenced blocks, paired with their result by `tool_call_id`:

````
```
tool_name(arg=value, ...)
⎿ result text
```
````

Pending or interrupted calls (no matching result) drop the `⎿` line.

Per-platform clipboard backend:

- macOS — `pbcopy`
- Windows — `clip`
- Linux/Wayland — `wl-copy`
- Linux/X11 — `xsel --clipboard --input`, falling back to `xclip -selection clipboard`

If none are available, the command reports the install hint.

## Implementation pointers

- `src/deepagent_tui/storage/db.py` — SQLite schema + helpers
- `src/deepagent_tui/commands/resume.py` — `/resume` and `_switch_thread`
- `src/deepagent_tui/commands/rewind.py` — `/rewind`
- `src/deepagent_tui/commands/copy.py` — `/copy` (also hosts the shared transcript/clipboard helpers)
- `src/deepagent_tui/commands/export.py` — `/export`
- `src/deepagent_tui/commands/new.py` — `/new`
