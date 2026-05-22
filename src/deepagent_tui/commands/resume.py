"""The /resume command — interactive thread picker to resume a past conversation."""

from __future__ import annotations

from datetime import datetime, timezone

from deepagent_tui.commands import command
from deepagent_tui.storage.db import get_thread, list_threads
from deepagent_tui.tui.screens import PickerItem
from deepagent_tui.ui.renderer import render_error, render_info


def _relative_time(ts: str | None) -> str:
    """Format a SQLite 'YYYY-MM-DD HH:MM:SS' timestamp as a relative
    string like '14 hours ago'. Returns empty string if unparseable."""
    if not ts:
        return ""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return ts
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if secs < 86400 * 30:
        d = secs // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"
    if secs < 86400 * 365:
        mo = secs // (86400 * 30)
        return f"{mo} month{'s' if mo != 1 else ''} ago"
    y = secs // (86400 * 365)
    return f"{y} year{'s' if y != 1 else ''} ago"


_TITLE_MAX = 80


def _row_title(t: dict) -> str:
    """Title line for the TUI picker — the last message collapsed to a
    single line and trimmed to TITLE_MAX chars with '...'. Falls back to
    the thread id when there is no message text."""
    last = (t.get("last_message") or "").strip()
    if not last:
        return t["id"]
    line = " ".join(last.split())  # collapse all whitespace (newlines, tabs) to single spaces
    if len(line) > _TITLE_MAX:
        line = line[:_TITLE_MAX].rstrip() + "..."
    return line


def _row_subtitle(t: dict, is_current: bool) -> str:
    """Subtitle line — '14 hours ago · <graph> · 12 msgs' (+ current marker)."""
    parts: list[str] = []
    rel = _relative_time(t.get("updated_at"))
    if rel:
        parts.append(rel)
    graph = (t.get("graph_id") or "").strip()
    if graph:
        parts.append(graph)
    msgs = t.get("message_count")
    if msgs is not None:
        parts.append(f"{msgs} msg{'s' if msgs != 1 else ''}")
    parts.append(t["id"][:8])
    line = "  ·  ".join(parts)
    if is_current:
        line = f"current  ·  {line}"
    return line


@command("resume", "Resume a past conversation thread")
async def cmd_resume(client, session, args: str) -> None:
    # If a thread ID was passed directly, try to resume it
    if args.strip():
        await _resume_by_id(client, session, args.strip())
        return

    threads = await list_threads(limit=200)
    # Skip empty threads — nothing to resume.
    threads = [t for t in threads if (t.get("message_count") or 0) > 0]
    if not threads:
        render_info("No saved threads to resume.")
        return

    picker = session.picker
    items = [
        PickerItem(
            title=_row_title(t),
            subtitle=_row_subtitle(t, t["id"] == session.thread_id),
            value=t["id"],
        )
        for t in threads
    ]
    chosen_id = await picker(
        items,
        "Resume session",
        subtitle="Showing the last message of each conversation",
    )
    if chosen_id is None:
        render_info("Cancelled.")
        return
    await _switch_thread(client, session, chosen_id)


async def _resume_by_id(client, session, thread_id: str) -> None:
    """Resume a thread by its full or partial ID."""
    # Try local DB first
    record = await get_thread(thread_id)
    if record:
        await _switch_thread(client, session, record["id"])
        return

    # Try partial match from local DB
    threads = await list_threads(limit=200)
    matches = [t for t in threads if t["id"].startswith(thread_id)]
    if len(matches) == 1:
        await _switch_thread(client, session, matches[0]["id"])
        return
    elif len(matches) > 1:
        render_error(f"Ambiguous thread ID prefix '{thread_id}' — {len(matches)} matches.")
        return

    # Try directly from server
    try:
        await client.get_thread(thread_id)
        await _switch_thread(client, session, thread_id)
    except Exception:
        render_error(f"Thread '{thread_id}' not found.")


async def _switch_thread(client, session, thread_id: str) -> None:
    """Switch the session to a different thread."""
    session.thread_id = thread_id
    session.messages = []
    session.input_tokens = 0
    session.output_tokens = 0
    session.total_cost = 0.0

    try:
        state = await client.get_thread_state(thread_id)
        messages = state.get("values", {}).get("messages", []) or []
    except Exception:
        messages = []

    # Clear the screen and re-render the past conversation in place so the
    # user picks up where they left off. The `Resumed thread:` header sits
    # above the replayed history so the user sees what just happened.
    await session.replay(messages, header=f"Resumed thread: {thread_id}")
