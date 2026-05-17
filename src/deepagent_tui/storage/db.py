"""SQLite-backed thread index for persisting thread metadata across sessions."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

DB_DIR = Path.home() / ".deepagent-tui"
DB_PATH = DB_DIR / "threads.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS threads (
    id           TEXT PRIMARY KEY,
    graph_id     TEXT NOT NULL,
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
    await db.commit()
    return db


async def upsert_thread(
    thread_id: str,
    graph_id: str,
    *,
    title: str | None = None,
    last_message: str | None = None,
    message_count: int | None = None,
) -> None:
    """Insert or update a thread record."""
    db = await _get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT id FROM threads WHERE id = ?", (thread_id,)
        )
        if row:
            parts: list[str] = ["updated_at = datetime('now')"]
            params: list[str | int] = []
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
                "INSERT INTO threads (id, graph_id, title, last_message, message_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    thread_id,
                    graph_id,
                    title or "",
                    last_message or "",
                    message_count or 0,
                ),
            )
        await db.commit()
    finally:
        await db.close()


async def list_threads(limit: int = 50) -> list[dict]:
    """Return recent threads ordered by last update."""
    db = await _get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, graph_id, title, last_message, message_count, "
            "created_at, updated_at FROM threads ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_thread(thread_id: str) -> dict | None:
    """Get a single thread record by ID."""
    db = await _get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, graph_id, title, last_message, message_count, "
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
