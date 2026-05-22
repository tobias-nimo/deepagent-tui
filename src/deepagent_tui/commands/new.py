"""The /new command — start a fresh thread."""

from __future__ import annotations

from deepagent_tui.commands import command


@command("new", "Clear screen and start a new conversation")
async def cmd_new(client, session, args: str) -> None:
    from deepagent_tui.ui.renderer import console, render_info

    console.clear()

    thread_id = await client.create_thread()
    session.thread_id = thread_id
    session.messages = []
    session.input_tokens = 0
    session.output_tokens = 0
    session.total_cost = 0.0

    # Don't index the empty thread — the stream worker upserts on first
    # message, so abandoned /new threads don't evict real conversations.
    # In the TUI, `_run_command` wipes the log and re-mounts the user
    # submission + acknowledgment after dispatch — but the CLI path needs
    # this line on its own to confirm thread creation.
    render_info(f"New thread: {thread_id}")
