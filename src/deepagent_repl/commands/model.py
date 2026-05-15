"""The /model command — show the active model."""

from __future__ import annotations

from deepagent_repl.commands import command
from deepagent_repl.ui.renderer import render_info


@command("model", "Show the active model")
async def cmd_model(client, session, args: str) -> None:
    if session.model:
        render_info(f"Using {session.model}")
    else:
        render_info("Model name is not available.")
