# Threads

How conversations are persisted, listed, resumed, forked, and exported.

## Storage

> `~/.deepagent-tui/threads.db` — SQLite schema overview, what each row holds, when rows are written/updated.

## Listing — `/threads`

> What columns appear, sort order, how the picker is navigated.

## Resuming — `/resume`

> No-arg picker vs. direct `/resume <thread_id>`. What state is restored from the server vs. the local index.

## Forking — `/fork`

> Browsing the message history, picking a user message, what happens server-side when you branch.

## Exporting — `/export`

> Output path (`.workspace/history/<thread_id>.md`), markdown structure, what's included.

## Implementation pointers

> `storage/db.py`, `commands/threads.py`, `commands/resume.py`, `commands/fork.py`, `commands/export.py`.
