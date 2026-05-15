"""The /fork command — browse conversation history and fork from an earlier point."""

from __future__ import annotations

from deepagent_repl.commands import command
from deepagent_repl.storage.db import upsert_thread
from deepagent_repl.ui.prompt import select_option_interactive
from deepagent_repl.ui.renderer import render_error, render_info


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

    render_info("Fetching conversation history...")

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

    # Sort by message position in thread, then keep last 10
    unique_checkpoints.sort(key=lambda x: x[0])
    unique_checkpoints = unique_checkpoints[-10:]

    # Build display options
    options = []
    for i, (idx, text, _entry) in enumerate(unique_checkpoints, 1):
        preview = text.replace("\n", " ").strip()
        if len(preview) > 70:
            preview = preview[:67] + "..."
        options.append(f"#{i}  {preview}")

    picker = getattr(session, "picker", None)
    if picker is not None:
        from deepagent_repl.tui.screens import PickerItem

        items = [
            PickerItem(
                title=preview.replace("\n", " ").strip()[:200],
                subtitle=f"message #{i}  ·  {len(preview)} chars",
                value=i - 1,
            )
            for i, (idx, preview, _entry) in enumerate(unique_checkpoints, 1)
        ]
        chosen_idx = await picker(items, "Fork from message")
        if chosen_idx is None:
            render_info("Cancelled.")
            return
        choice = chosen_idx
    else:
        render_info("Select a message to fork from (↑↓ to move, Enter to confirm, Ctrl+C to cancel):")
        chosen = await select_option_interactive(options)
        if chosen is None:
            render_info("Cancelled.")
            return
        choice = options.index(chosen)

    idx, text, checkpoint_entry = unique_checkpoints[choice]

    render_info(f"Forking from message #{choice + 1}: {text[:60]}...")

    try:
        values = checkpoint_entry.get("values", {})
        messages = values.get("messages", [])
        fork_messages = messages[: idx + 1]

        new_thread_id = await client.copy_thread_with_messages(fork_messages)

        session.thread_id = new_thread_id
        session.messages = []
        session.input_tokens = 0
        session.output_tokens = 0
        session.total_cost = 0.0

        await upsert_thread(new_thread_id, session.graph_id or "")

        render_info(f"Forked to new thread: {new_thread_id}")
        render_info(f"  {len(fork_messages)} message(s) preserved.")
        render_info("You can now continue the conversation from this point.")

    except Exception as e:
        msg = str(e)
        if "no assigned graph ID" in msg or "graph_id" in msg.lower():
            render_info("Fork failed: thread has no graph ID. Ensure at least one run has been made before forking.")
        else:
            render_error(f"Fork failed: {e}")
