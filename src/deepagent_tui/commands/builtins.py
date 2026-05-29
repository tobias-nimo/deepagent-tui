"""Built-in commands: /clear, /exit."""

from __future__ import annotations

import sys

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import console


@command("clear", "Clear the terminal screen")
async def cmd_clear(client, session, args: str) -> None:
    console.clear()


@command("exit", "Exit the TUI")
async def cmd_exit(client, session, args: str) -> None:
    # Ask the TUI to stop cleanly so `run()` returns and `launch_tui` can print
    # the resume hint after the alt-screen is torn down. Fall back to a hard
    # exit only when the app callback isn't wired (e.g. non-TUI contexts).
    if session.exit_app is not None:
        session.exit_app()
    else:
        sys.exit(0)
