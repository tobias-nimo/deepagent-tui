"""The /export command — copy the full conversation to the clipboard."""

from __future__ import annotations

from deepagent_tui.commands import command
from deepagent_tui.commands.copy import (
    build_full_transcript,
    copy_to_clipboard,
    fetch_messages,
)
from deepagent_tui.ui.renderer import render_error, render_info


@command("export", "Copy the entire conversation to clipboard")
async def cmd_export(client, session, args: str) -> None:
    messages = await fetch_messages(client, session)
    if messages is None:
        return

    transcript = build_full_transcript(messages)
    if not transcript.strip():
        render_info("Nothing to export.")
        return

    if copy_to_clipboard(transcript):
        render_info("Conversation copied to clipboard.")
    else:
        render_error("Failed to copy to clipboard (install xsel, xclip, or wl-clipboard)")
