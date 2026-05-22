"""Shared rich Console + helpers used by command handlers.

The CLI falls through to the rich Console; the TUI installs a mount sink via
`set_mount_sink` so each `render_info` / `render_error` / `render_renderable`
call lands as a single Textual widget. That single-widget contract is what
lets a multi-line message share one `⎿` corner with subsequent lines
aligned beneath it — splitting it across widgets would leave a top-margin
gap between each line.
"""
from __future__ import annotations

from typing import Callable

from rich.console import Console, RenderableType
from rich.text import Text

console = Console()

_INDENT = "  "
_CORNER_ALIGN = _INDENT + "   "  # 5 spaces — aligns under text after "⎿  "

_mount_sink: Callable[[RenderableType], None] | None = None


def set_mount_sink(fn: Callable[[RenderableType], None] | None) -> None:
    """Install (or clear) a callback that mounts a renderable as one widget."""
    global _mount_sink
    _mount_sink = fn


def _corner_block(message: str, *, style: str) -> Text:
    """`⎿`-prefixed block: first line next to a dim corner, rest aligned under.
    The marker stays dim; the body inherits `style`. The separator between
    marker and body lives in the body's styled segment because a trailing
    space in a `dim`-styled segment can be visually swallowed by the next
    segment's styling — keeping it on the body side preserves the gap."""
    out = Text()
    out.append(_INDENT)
    out.append("⎿", style="dim")
    lines = message.splitlines() or [""]
    for i, ln in enumerate(lines):
        if i:
            out.append("\n")
            out.append(_CORNER_ALIGN)
            out.append(ln, style=style)
        else:
            out.append("  " + ln, style=style)
    return out


def render_renderable(renderable: RenderableType) -> None:
    """Mount an arbitrary renderable (e.g. a rich Table) as one message."""
    if _mount_sink is not None:
        _mount_sink(renderable)
    else:
        console.print(renderable)


def render_error(message: str) -> None:
    """Render an error line under a dim `⎿` corner; body in red."""
    render_renderable(_corner_block(message, style="red"))


def render_info(message: str) -> None:
    """Render an informational line under a dim `⎿` corner; body in dim."""
    render_renderable(_corner_block(message, style="dim"))
