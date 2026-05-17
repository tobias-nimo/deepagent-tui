from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

import deepagent_tui.ui.theme as _theme


@dataclass
class PickerItem:
    """One row in a picker — a bold title line, a dim subtitle line, and the
    opaque value that's returned when the user selects this row."""

    title: str
    subtitle: str
    value: Any


class PickerScreen(Screen[Any]):
    """Full-screen list picker styled after Claude Code's /resume picker.

    Heading line at the top ("Resume session (N of M)"), a search line
    underneath, a scrolling list of title/subtitle rows, and a footer
    hint with keyboard shortcuts.

    All key handling lives in `on_key`. Nothing on the screen is
    focusable, so every key reliably reaches us — type to filter, ↑↓ to
    move, Enter to select, Esc/Ctrl+C to cancel.
    """

    DEFAULT_CSS = """
    PickerScreen { background: $background; layout: vertical; }

    #picker-root { padding: 1 2; height: 1fr; background: $background; }

    #picker-title {
        height: auto;
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #picker-search {
        height: 3;
        border: round #4b5563;
        background: $background;
        color: $text;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    #picker-rows {
        height: 1fr;
        background: $background;
        scrollbar-size: 0 0;
        padding: 0;
    }

    .picker-row {
        height: auto;
        padding: 0 0 1 0;
        background: $background;
        color: $text;
    }

    .picker-empty {
        height: auto;
        padding: 1 0;
        color: $text-muted;
    }

    #picker-footer {
        height: auto;
        color: $text-muted;
        padding: 0;
    }
    """

    def __init__(
        self,
        items: list[PickerItem],
        heading: str = "Select",
        search_placeholder: str = "Search chats...",
        hint: str | None = None,
        max_visible: int | None = None,
    ) -> None:
        super().__init__()
        self._items = items
        self._heading = heading
        self._search_placeholder = search_placeholder
        self._hint = (
            hint
            or "↑↓ to move  ·  Enter to select  ·  Type to search  ·  Esc to cancel"
        )
        self._max_visible = max_visible
        self._query: str = ""
        self._filtered: list[int] = self._compute_filtered()
        self._selected: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-root"):
            yield Static("", id="picker-title")
            yield Static("", id="picker-search")
            yield VerticalScroll(id="picker-rows")
            yield Static(self._hint, id="picker-footer")

    async def on_mount(self) -> None:
        # Keep keys reaching this Screen — descendants that are focusable
        # by default (VerticalScroll, etc.) would otherwise swallow up/down.
        rows = self.query_one("#picker-rows", VerticalScroll)
        rows.can_focus = False
        self.can_focus = True
        self._refresh_title()
        self._refresh_search()
        await self._rebuild_rows()
        self.set_focus(None)

    # ── input ──────────────────────────────────────────────────────────────

    async def on_key(self, event: events.Key) -> None:
        key = event.key

        if key in ("escape", "ctrl+c"):
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return

        if key in ("up", "ctrl+p", "shift+tab"):
            event.stop()
            event.prevent_default()
            await self._move_selection(-1)
            return

        if key in ("down", "ctrl+n", "tab"):
            event.stop()
            event.prevent_default()
            await self._move_selection(+1)
            return

        if key == "enter":
            event.stop()
            event.prevent_default()
            self._select_current()
            return

        if key in ("backspace", "ctrl+h"):
            event.stop()
            event.prevent_default()
            if self._query:
                self._query = self._query[:-1]
                await self._apply_filter()
                self._refresh_search()
            return

        char = event.character
        if char and len(char) == 1 and char.isprintable():
            event.stop()
            event.prevent_default()
            self._query += char.lower()
            await self._apply_filter()
            self._refresh_search()
            return

    # ── filtering / navigation ─────────────────────────────────────────────

    def _compute_filtered(self) -> list[int]:
        """Indices of items matching the current query, capped at
        max_visible (when set). Used to cap both the default view (most
        recent N) and search results (top N matches)."""
        if not self._query:
            indices = list(range(len(self._items)))
        else:
            q = self._query
            indices = [
                i
                for i, it in enumerate(self._items)
                if q in it.title.lower() or q in it.subtitle.lower()
            ]
        if self._max_visible is not None:
            indices = indices[: self._max_visible]
        return indices

    async def _apply_filter(self) -> None:
        self._filtered = self._compute_filtered()
        self._selected = 0
        await self._rebuild_rows()
        self._refresh_title()

    async def _move_selection(self, delta: int) -> None:
        if not self._filtered:
            return
        self._selected = (self._selected + delta) % len(self._filtered)
        await self._rebuild_rows()
        self._refresh_title()
        self._scroll_to_selected()

    def _select_current(self) -> None:
        if not self._filtered:
            self.dismiss(None)
            return
        item = self._items[self._filtered[self._selected]]
        self.dismiss(item.value)

    # ── rendering ──────────────────────────────────────────────────────────

    def _refresh_title(self) -> None:
        title = Text()
        title.append(self._heading, style="bold")
        self.query_one("#picker-title", Static).update(title)

    def _refresh_search(self) -> None:
        accent = _theme.current_theme().accent
        line = Text()
        line.append("🔍  ", style="bold")
        if self._query:
            line.append(self._query, style=f"bold {accent}")
            line.append("▍", style=accent)
        else:
            line.append(self._search_placeholder, style="dim")
        self.query_one("#picker-search", Static).update(line)

    async def _rebuild_rows(self) -> None:
        container = self.query_one("#picker-rows", VerticalScroll)
        # Await removal so the previous children are fully gone before we
        # mount their replacements — without this, rapid keystrokes can
        # collide (DuplicateIds, double-mounted rows, etc.).
        await container.remove_children()

        if not self._filtered:
            container.mount(
                Static(Text("No matches.", style="dim"), classes="picker-empty")
            )
            return

        for i, item_idx in enumerate(self._filtered):
            item = self._items[item_idx]
            container.mount(
                Static(
                    self._render_row(item, selected=(i == self._selected)),
                    classes="picker-row",
                )
            )

    def _render_row(self, item: PickerItem, *, selected: bool) -> RenderableType:
        accent = _theme.current_theme().accent
        if selected:
            head = Text()
            head.append("❯ ", style=f"bold {accent}")
            head.append(item.title, style=f"bold {accent}")
        else:
            head = Text(f"  {item.title}")
        sub = Text(f"  {item.subtitle}", style="dim")
        return Group(head, sub)

    def _scroll_to_selected(self) -> None:
        container = self.query_one("#picker-rows", VerticalScroll)
        children = list(container.children)
        if 0 <= self._selected < len(children):
            container.scroll_to_widget(children[self._selected], animate=False)
