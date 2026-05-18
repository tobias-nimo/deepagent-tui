"""Built-in commands: /commands, /clear, /exit, /status."""

from __future__ import annotations

import sys

from rich.table import Table

import deepagent_tui.ui.theme as _theme
from deepagent_tui.commands import builtin_commands, command
from deepagent_tui.ui.renderer import console, render_info


@command("commands", "Show available commands")
async def cmd_commands(client, session, args: str) -> None:
    cmds = builtin_commands()
    if not cmds:
        render_info("No commands registered.")
        return

    name_width = max((len(name) + 1 for name in cmds), default=10)

    table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
    table.add_column("Command", style=f"bold {_theme.ACCENT_COLOR}", min_width=name_width)
    table.add_column("Description", style="dim", overflow="fold")

    for name, desc in sorted(cmds.items()):
        table.add_row(f"/{name}", desc or "—")

    console.print()
    console.print(table)
    console.print()


@command("clear", "Clear the terminal screen")
async def cmd_clear(client, session, args: str) -> None:
    console.clear()


@command("exit", "Exit the TUI")
async def cmd_exit(client, session, args: str) -> None:
    render_info("Goodbye!")
    sys.exit(0)


@command("status", "Show connection and session info")
async def cmd_status(client, session, args: str) -> None:
    from deepagent_tui.config import settings
    from deepagent_tui.utils.cost import format_cost, format_tokens

    render_info(f"Server:    {settings.langgraph_url}")
    render_info(f"Graph:     {session.graph_id or 'not connected'}")
    render_info(f"Assistant: {session.assistant_id or 'not connected'}")
    render_info(f"Thread:    {session.thread_id or 'none'}")
    render_info(f"Model:     {session.model or 'unknown'}")
    render_info(f"Status:    {session.status}")
    in_tok = format_tokens(session.input_tokens)
    out_tok = format_tokens(session.output_tokens)
    cost = format_cost(session.total_cost)
    render_info(f"Tokens:    {in_tok} in / {out_tok} out")
    render_info(f"Cost:      {cost}")
