"""The /export command — copy the full conversation to the clipboard."""

from __future__ import annotations

import os

from deepagent_tui.commands import command
from deepagent_tui.commands.copy import (
    build_full_transcript,
    copy_to_clipboard,
    fetch_messages,
)
from deepagent_tui.ui.renderer import render_error, render_info


def _collapse_home(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~/" + path[len(home) + 1 :]
    return path


def _build_banner(session) -> str:
    from pyfiglet import Figlet

    graph = (session.graph_id or "deepagent").strip()
    try:
        art = Figlet(font="ansi_shadow", width=200).renderText(f"> {graph}").rstrip("\n")
    except Exception:
        art = f"> {graph}"
    lines = [ln for ln in art.split("\n") if ln.rstrip()]

    parts = list(lines)
    if session.workspace_root:
        parts.append("")
        parts.append(_collapse_home(session.workspace_root))
    return "\n".join(parts)


@command("export", "Copy the entire conversation to clipboard")
async def cmd_export(client, session, args: str) -> None:
    messages = await fetch_messages(client, session)
    if messages is None:
        return

    transcript = build_full_transcript(messages)
    if not transcript.strip():
        render_info("Nothing to export.")
        return

    full = f"{_build_banner(session)}\n\n{transcript}"

    if copy_to_clipboard(full):
        render_info("Conversation copied to clipboard.")
    else:
        render_error("Failed to copy to clipboard (install xsel, xclip, or wl-clipboard)")
