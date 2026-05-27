"""Built-in commands: /clear, /exit."""

from __future__ import annotations

import sys

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import console, render_info


@command("clear", "Clear the terminal screen")
async def cmd_clear(client, session, args: str) -> None:
    console.clear()


@command("exit", "Exit the TUI")
async def cmd_exit(client, session, args: str) -> None:
    render_info("Goodbye!")
    sys.exit(0)
