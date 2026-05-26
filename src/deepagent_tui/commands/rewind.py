"""The /rewind command — browse conversation history and rewind to an earlier point."""

from __future__ import annotations

from deepagent_tui.commands import command
from deepagent_tui.tui.screens import PickerItem
from deepagent_tui.ui.renderer import render_error, render_info


def _extract_text(content) -> str:
    """Extract plain text from message content (str or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content)


@command("rewind", "Browse history and rewind to an earlier message")
async def cmd_rewind(client, session, args: str) -> None:
    if not session.thread_id:
        render_error("No active thread.")
        return

    try:
        history = await client.get_thread_history(session.thread_id)
    except Exception as e:
        msg = str(e)
        if "no assigned graph ID" in msg or "graph_id" in msg.lower():
            render_error("This thread has no history to rewind to (no runs have been made yet).")
        else:
            render_error(f"Failed to fetch history: {e}")
        return

    if not history:
        render_info("No history found for this thread.")
        return

    # Messages removed via RemoveMessage (e.g. /compact's internal prompt) are
    # gone from current state but still live in earlier checkpoints. Restrict
    # rewind candidates to IDs that survived into the latest snapshot so the
    # picker doesn't expose internal prompts the user never sent.
    live_ids: set[str] = set()
    try:
        current = await client.get_thread_state(session.thread_id)
        for m in current.get("values", {}).get("messages", []) or []:
            if isinstance(m, dict) and isinstance(m.get("id"), str):
                live_ids.add(m["id"])
    except Exception:
        live_ids = set()

    # Extract checkpoints that contain user messages.
    user_checkpoints: list[tuple[int, str, dict]] = []

    for entry in history:
        values = entry.get("values", {})
        messages = values.get("messages", [])
        if not messages:
            continue

        for i, msg in enumerate(messages):
            role = msg.get("role") or msg.get("type", "")
            if role in ("user", "human"):
                mid = msg.get("id")
                if live_ids and (not isinstance(mid, str) or mid not in live_ids):
                    continue
                text = _extract_text(msg.get("content", ""))
                if text.strip():
                    already = any(uc[0] == i and uc[1] == text for uc in user_checkpoints)
                    if not already:
                        user_checkpoints.append((i, text, entry))

    # Deduplicate — keep the earliest checkpoint for each unique user message text
    seen_texts: set[str] = set()
    unique_checkpoints: list[tuple[int, str, dict]] = []
    for idx, text, entry in user_checkpoints:
        key = f"{idx}:{text[:100]}"
        if key not in seen_texts:
            seen_texts.add(key)
            unique_checkpoints.append((idx, text, entry))

    if not unique_checkpoints:
        render_info("No user messages found in history.")
        return

    # Sort by message position in thread — show every user turn so the
    # user can rewind to any earlier point (picker is filterable).
    unique_checkpoints.sort(key=lambda x: x[0])

    items = [
        PickerItem(
            title=preview.replace("\n", " ").strip()[:200],
            subtitle=f"message #{i}  ·  {len(preview)} chars",
            value=i - 1,
        )
        for i, (idx, preview, _entry) in enumerate(unique_checkpoints, 1)
    ]
    choice = await session.picker(
        items,
        "Rewind to message",
        subtitle="Restore the conversation to the point before…",
        search_placeholder="Search messages...",
    )
    if choice is None:
        render_info("Cancelled.")
        return

    idx, text, checkpoint_entry = unique_checkpoints[choice]

    try:
        values = checkpoint_entry.get("values", {})
        messages = values.get("messages", [])
        # Restore to the point *before* the chosen user message — that turn
        # is what the user wants to edit and resend, so drop it (and anything
        # after) from the new thread.
        rewind_messages = messages[:idx]

        new_thread_id = await client.copy_thread_with_messages(
            rewind_messages, graph_id=session.graph_id,
        )

        session.thread_id = new_thread_id
        session.messages = []
        session.input_tokens = 0
        session.output_tokens = 0
        session.total_cost = 0.0

        # Don't index the rewind yet — the stream worker upserts on the next
        # user message. If the rewind is abandoned, it shouldn't take up a
        # retention slot. Pass a header so `⎿ Rewound to message #m.`
        # appears above the replayed history.
        await session.replay(
            rewind_messages,
            header=f"Rewound to message #{choice + 1} (new thread {new_thread_id}).",
        )

        # Pre-fill the chat bar with the selected user message so the user
        # can edit it and resend (or just hit enter to replay verbatim).
        if text.strip() and session.set_input is not None:
            session.set_input(text.strip())

    except Exception as e:
        msg = str(e)
        if "no assigned graph ID" in msg or "graph_id" in msg.lower():
            render_info("Rewind failed: thread has no graph ID. Ensure at least one run has been made before rewinding.")
        else:
            render_error(f"Rewind failed: {e}")
