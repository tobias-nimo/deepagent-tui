"""The /fork command — browse conversation history and fork from an earlier point."""

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


@command("fork", "Browse history and fork from an earlier message")
async def cmd_fork(client, session, args: str) -> None:
    if not session.thread_id:
        render_error("No active thread.")
        return

    try:
        history = await client.get_thread_history(session.thread_id)
    except Exception as e:
        msg = str(e)
        if "no assigned graph ID" in msg or "graph_id" in msg.lower():
            render_error("This thread has no history to fork from (no runs have been made yet).")
        else:
            render_error(f"Failed to fetch history: {e}")
        return

    if not history:
        render_info("No history found for this thread.")
        return

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
    # user can fork from any earlier point (picker is filterable).
    unique_checkpoints.sort(key=lambda x: x[0])

    items = [
        PickerItem(
            title=preview.replace("\n", " ").strip()[:200],
            subtitle=f"message #{i}  ·  {len(preview)} chars",
            value=i - 1,
        )
        for i, (idx, preview, _entry) in enumerate(unique_checkpoints, 1)
    ]
    choice = await session.picker(items, "Fork from message")
    if choice is None:
        render_info("Cancelled.")
        return

    idx, text, checkpoint_entry = unique_checkpoints[choice]

    try:
        values = checkpoint_entry.get("values", {})
        messages = values.get("messages", [])
        # Keep the chosen user message AND the assistant turn that responded to
        # it (which may include tool calls/results). Stop at the next user
        # message — that's where the branch should diverge.
        end = len(messages)
        for j in range(idx + 1, len(messages)):
            role = messages[j].get("role") or messages[j].get("type", "")
            if role in ("user", "human"):
                end = j
                break
        fork_messages = messages[:end]

        new_thread_id = await client.copy_thread_with_messages(
            fork_messages, graph_id=session.graph_id,
        )

        session.thread_id = new_thread_id
        session.messages = []
        session.input_tokens = 0
        session.output_tokens = 0
        session.total_cost = 0.0

        # Don't index the fork yet — the stream worker upserts on the next
        # user message. If the fork is abandoned, it shouldn't take up a
        # retention slot.
        await session.replay(fork_messages)
        render_info(f"Forked from message #{choice + 1}.")

        # Pre-fill the chat bar with the next user message from the original
        # conversation — the one the branch would have diverged on — so the
        # user can edit it and resend (or just hit enter to replay).
        if end < len(messages):
            next_text = _extract_text(messages[end].get("content", "")).strip()
            if next_text and session.set_input is not None:
                session.set_input(next_text)

    except Exception as e:
        msg = str(e)
        if "no assigned graph ID" in msg or "graph_id" in msg.lower():
            render_info("Fork failed: thread has no graph ID. Ensure at least one run has been made before forking.")
        else:
            render_error(f"Fork failed: {e}")
