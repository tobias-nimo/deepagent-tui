"""The /settings command — open the three-tab settings screen."""

from __future__ import annotations

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import render_error


@command("settings", "Open the settings screen")
async def cmd_settings(client, session, args: str) -> None:
    if session.show_settings is None:
        render_error("Settings screen is not available outside the TUI.")
        return
    await session.show_settings()
