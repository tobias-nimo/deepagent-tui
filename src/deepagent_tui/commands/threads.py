"""The /threads command — list saved threads."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text

from deepagent_tui.commands import command
from deepagent_tui.storage.db import list_threads
from deepagent_tui.ui.renderer import console, render_info


@command("threads", "List saved conversation threads")
async def cmd_threads(client, session, args: str) -> None:
    threads = await list_threads(limit=10)
    if not threads:
        render_info("No saved threads.")
        return

    table = Table(show_header=True, header_style="bold", expand=False, padding=(0, 1))
    table.add_column("Thread ID", width=16, no_wrap=True)
    table.add_column("Graph", width=16, no_wrap=True)
    table.add_column("Msgs", justify="right", width=4, no_wrap=True)
    table.add_column("Last Message", width=36, no_wrap=True)
    table.add_column("Updated", width=19, no_wrap=True)

    for t in threads:
        is_current = t["id"] == session.thread_id
        tid_short = t["id"][:12] + "…"
        tid_display = f"* {tid_short}" if is_current else f"  {tid_short}"

        last_msg = t["last_message"] or ""
        if len(last_msg) > 35:
            last_msg = last_msg[:34] + "…"

        style = "bold green" if is_current else ""
        table.add_row(
            Text(tid_display, style=style),
            t["graph_id"],
            str(t["message_count"]),
            last_msg,
            t["updated_at"] or "",
        )

    console.print()
    console.print(table)
    console.print()
