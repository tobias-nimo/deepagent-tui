"""Shared rich Console + helpers used by command handlers.

The TUI captures everything written to `console` and replays it inline,
so commands keep using `render_error` / `render_info` and the output
lands in the chat transcript.
"""
from __future__ import annotations

from rich.console import Console
from rich.text import Text

console = Console()


def render_error(message: str) -> None:
    """Render an error message."""
    console.print(Text(f"Error: {message}", style="bold red"))


def render_info(message: str) -> None:
    """Render an informational message."""
    console.print(Text(message, style="dim"))
