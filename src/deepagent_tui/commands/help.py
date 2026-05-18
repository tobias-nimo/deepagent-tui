"""The /help command — open a full-screen help view with tips and shortcuts."""

from __future__ import annotations

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import render_error


@command("help", "Show tips and keyboard shortcuts")
async def cmd_help(client, session, args: str) -> None:
    if session.show_help is None:
        render_error("Help screen is not available outside the TUI.")
        return
    await session.show_help()
