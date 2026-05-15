"""The /theme command — choose a built-in UI theme."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text

from deepagent_repl.commands import command
from deepagent_repl.ui.renderer import console, render_error, render_info
from deepagent_repl.ui.theme import (
    THEMES,
    available_themes,
    current_theme,
    persist_theme,
    set_theme,
)


def _swatch(rgb: tuple[int, int, int]) -> Text:
    r, g, b = rgb
    return Text("██", style=f"#{r:02x}{g:02x}{b:02x}")


@command("theme", "Set the UI theme: /theme [name]")
async def cmd_theme(client, session, args: str) -> None:
    name = args.strip().lower()
    current = current_theme()

    if not name:
        render_info(f"Current theme: {current.name}")
        table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
        table.add_column("name")
        table.add_column("gradient")
        table.add_column("accent")
        table.add_column("command")

        for theme_name in available_themes():
            t = THEMES[theme_name]
            marker = "● " if theme_name == current.name else "  "
            name_cell = Text(f"{marker}{theme_name}", style="bold" if theme_name == current.name else "")
            gradient_cell = Text.assemble(_swatch(t.gradient_start), ("  ", ""), _swatch(t.gradient_end))
            accent_cell = Text("████", style=t.accent)
            command_cell = Text("████", style=t.command)
            table.add_row(name_cell, gradient_cell, accent_cell, command_cell)

        console.print()
        console.print(table)
        console.print()
        render_info("Apply with /theme <name>")
        return

    if set_theme(name):
        persist_theme(name)
        render_info(f"Theme set to: {name}")
    else:
        render_error(f"Unknown theme: {name}")
        render_info(f"Available: {', '.join(available_themes())}")
