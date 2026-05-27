"""The /compact command — summarise older messages via SummarizationToolMiddleware.

The TUI intercepts this command in `_run_command` and routes through the
streaming pipeline (mirrors the dynamic-skill branch). This stub handler
exists so the command appears in autocomplete and in /help's Commands
tab; it only runs if invoked outside the TUI.
"""

from __future__ import annotations

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import render_error


@command("compact", "Summarise older messages to free up context")
async def cmd_compact(client, session, args: str) -> None:
    render_error("/compact is only available inside the TUI.")
