"""The /new command — start a fresh thread."""

from __future__ import annotations

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import render_info


@command("new", "Clear screen and start a new conversation")
async def cmd_new(client, session, args: str) -> None:
    from deepagent_tui.ui.renderer import console

    console.clear()

    thread_id = await client.create_thread()
    session.thread_id = thread_id
    session.messages = []
    session.input_tokens = 0
    session.output_tokens = 0
    session.total_cost = 0.0

    # Don't index the empty thread — the stream worker upserts on first
    # message, so abandoned /new threads don't evict real conversations.
    render_info(f"New thread: {thread_id}")
