"""The /theme command — pick or apply a UI theme."""

from __future__ import annotations

from rich.text import Text

from deepagent_tui.commands import command
from deepagent_tui.tui.screens import PickerItem
from deepagent_tui.ui.renderer import render_error, render_info
from deepagent_tui.ui.theme import (
    THEMES,
    available_themes,
    current_theme,
    persist_theme,
    set_theme,
)

_BAR_WIDTH = 14


def _gradient_bar(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    width: int = _BAR_WIDTH,
) -> Text:
    """Interpolated color bar from `start` to `end` over `width` characters."""
    out = Text()
    span = max(1, width - 1)
    sr, sg, sb = start
    er, eg, eb = end
    for i in range(width):
        t = i / span
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        out.append("█", style=f"#{r:02x}{g:02x}{b:02x}")
    return out


def _theme_subtitle(theme_name: str, is_current: bool) -> Text:
    """Picker subtitle for a theme row — gradient bar + accent/command swatches,
    with a `current` marker for the active theme."""
    t = THEMES[theme_name]
    sub = Text()
    sub.append_text(_gradient_bar(t.gradient_start, t.gradient_end))
    sub.append("  ", style="dim")
    sub.append("██", style=t.accent)
    sub.append("  ", style="dim")
    sub.append("██", style=t.command)
    if is_current:
        sub.append("  ·  current", style="dim")
    return sub


@command("theme", "Set the UI theme: /theme [name]")
async def cmd_theme(client, session, args: str) -> None:
    name = args.strip().lower()

    if not name:
        current = current_theme()
        items = [
            PickerItem(
                title=tn,
                subtitle=_theme_subtitle(tn, is_current=(tn == current.name)),
                value=tn,
            )
            for tn in available_themes()
        ]
        chosen = await session.picker(
            items,
            "Themes",
            subtitle="Pick a theme to apply…",
            search_placeholder="Search themes...",
        )
        if chosen is None:
            render_info("Cancelled.")
            return
        if set_theme(chosen):
            persist_theme(chosen)
            render_info(f"Theme set to: {chosen}")
        else:
            render_error(f"Unknown theme: {chosen}")
        return

    if set_theme(name):
        persist_theme(name)
        render_info(f"Theme set to: {name}")
    else:
        render_error(f"Unknown theme: {name}")
        render_info(f"Available: {', '.join(available_themes())}")
