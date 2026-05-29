"""SQLite-backed thread index for persisting thread metadata across sessions."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

DB_DIR = Path.home() / ".deepagent-tui"
DB_PATH = DB_DIR / "threads.db"

# Cap the local index at the N most-recently-updated threads. Every
# `upsert_thread` trims older rows past this limit so the DB stays bounded
# and `/resume` never balloons with stale entries.
MAX_THREADS = 20

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS threads (
    id           TEXT PRIMARY KEY,
    graph_id     TEXT NOT NULL,
    workspace    TEXT,
    title        TEXT NOT NULL DEFAULT '',
    last_message TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


async def _get_db() -> aiosqlite.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute(_CREATE_TABLE)
    # Migrate pre-scoping databases that predate the `workspace` column. SQLite
    # has no "ADD COLUMN IF NOT EXISTS", so probe the schema first.
    cols = await db.execute_fetchall("PRAGMA table_info(threads)")
    if not any(c["name"] == "workspace" for c in cols):
        await db.execute("ALTER TABLE threads ADD COLUMN workspace TEXT")
    await db.commit()
    return db


async def upsert_thread(
    thread_id: str,
    graph_id: str,
    *,
    workspace: str | None = None,
    title: str | None = None,
    last_message: str | None = None,
    message_count: int | None = None,
) -> None:
    """Insert or update a thread record.

    `workspace` is the agent's workspace root, which is often unknown when the
    thread is first created (it only arrives in server state after the first
    message). It's written only when provided, so a later upsert backfills it
    without an earlier `None` clobbering a known value.
    """
    db = await _get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT id FROM threads WHERE id = ?", (thread_id,)
        )
        if row:
            parts: list[str] = ["updated_at = datetime('now')"]
            params: list[str | int] = []
            if workspace is not None:
                parts.append("workspace = ?")
                params.append(workspace)
            if title is not None:
                parts.append("title = ?")
                params.append(title)
            if last_message is not None:
                parts.append("last_message = ?")
                params.append(last_message)
            if message_count is not None:
                parts.append("message_count = ?")
                params.append(message_count)
            params.append(thread_id)
            await db.execute(
                f"UPDATE threads SET {', '.join(parts)} WHERE id = ?", params
            )
        else:
            await db.execute(
                "INSERT INTO threads (id, graph_id, workspace, title, last_message, message_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    graph_id,
                    workspace,
                    title or "",
                    last_message or "",
                    message_count or 0,
                ),
            )
        # Enforce the retention cap after every write: keep the MAX_THREADS
        # most-recently-updated rows, drop the rest. Cheap to run even when
        # the row count is already within the cap.
        await db.execute(
            "DELETE FROM threads WHERE id NOT IN "
            "(SELECT id FROM threads ORDER BY updated_at DESC, id DESC LIMIT ?)",
            (MAX_THREADS,),
        )
        await db.commit()
    finally:
        await db.close()


async def list_threads(
    limit: int = 50,
    *,
    graph_id: str | None = None,
    workspace: str | None = None,
) -> list[dict]:
    """Return recent threads ordered by last update.

    `graph_id` / `workspace` scope the result to the current agent and (when
    known) workspace. Each filter is applied only when provided, so callers
    that can't classify the current session (e.g. workspace not yet reported by
    the server) simply pass it as None and get the broader, unfiltered set.
    """
    where: list[str] = []
    params: list[str | int] = []
    if graph_id is not None:
        where.append("graph_id = ?")
        params.append(graph_id)
    if workspace is not None:
        where.append("workspace = ?")
        params.append(workspace)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    db = await _get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, graph_id, workspace, title, last_message, message_count, "
            f"created_at, updated_at FROM threads{clause} ORDER BY updated_at DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_thread(thread_id: str) -> dict | None:
    """Get a single thread record by ID."""
    db = await _get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, graph_id, workspace, title, last_message, message_count, "
            "created_at, updated_at FROM threads WHERE id = ?",
            (thread_id,),
        )
        return dict(rows[0]) if rows else None
    finally:
        await db.close()


async def delete_thread(thread_id: str) -> None:
    """Delete a thread record."""
    db = await _get_db()
    try:
        await db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        await db.commit()
    finally:
        await db.close()
