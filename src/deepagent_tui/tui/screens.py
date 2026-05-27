from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Static

import deepagent_tui.ui.theme as _theme


@dataclass
class PickerItem:
    """One row in a picker — a bold title line, a dim subtitle line, and the
    opaque value that's returned when the user selects this row. Subtitle
    may be a Rich `Text` so callers can inject inline styling (e.g. the
    /theme picker's gradient swatches)."""

    title: str
    subtitle: Text | str
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
        padding: 0;
    }

    #picker-subtitle {
        height: auto;
        color: $text-muted;
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
        subtitle: str | None = None,
    ) -> None:
        super().__init__()
        self._items = items
        self._heading = heading
        self._subtitle = subtitle
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
            if self._subtitle:
                yield Static(Text(self._subtitle, style="dim"), id="picker-subtitle")
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
            indices = []
            for i, it in enumerate(self._items):
                sub = it.subtitle.plain if isinstance(it.subtitle, Text) else it.subtitle
                if q in it.title.lower() or q in sub.lower():
                    indices.append(i)
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
        line.append("⌕ ", style="dim")
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
                Static(Text("No matches", style="dim"), classes="picker-empty")
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
        sub = Text("  ")
        if isinstance(item.subtitle, Text):
            sub.append_text(item.subtitle)
        else:
            sub.append(item.subtitle, style="dim")
        return Group(head, sub)

    def _scroll_to_selected(self) -> None:
        container = self.query_one("#picker-rows", VerticalScroll)
        children = list(container.children)
        if 0 <= self._selected < len(children):
            widget = children[self._selected]
            # `_rebuild_rows` just remounted everything; widget regions
            # aren't computed until after the next refresh, so scrolling now
            # would be a no-op. Defer to the post-layout phase.
            self.call_after_refresh(container.scroll_to_widget, widget, animate=False)


class HelpScreen(Screen[None]):
    """Full-screen help view: keyboard shortcuts and tips.

    Static content (no selection); dismissed with Esc / Ctrl+C / q.
    """

    DEFAULT_CSS = """
    HelpScreen { background: $background; layout: vertical; }

    #help-root { padding: 1 2; height: 1fr; background: $background; }

    #help-title {
        height: auto;
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #help-body {
        height: 1fr;
        background: $background;
        scrollbar-size: 0 0;
        padding: 0;
    }

    #help-body Static {
        height: auto;
        background: $background;
        color: $text;
        padding: 0 0 1 0;
    }

    #help-footer {
        height: auto;
        color: $text-muted;
        padding: 0;
    }
    """

    SHORTCUTS: list[tuple[str, str]] = [
        ("Enter", "Send the current message"),
        ("Shift+Enter", "Insert a newline (multi-line input)"),
        ("Tab", "Accept the highlighted slash-command autocomplete"),
        ("Esc", "Cancel a streaming run and restore the typed message"),
        ("Esc Esc", "Drop pending image attachments"),
        ("Ctrl+L", "Clear the message log (same as /clear)"),
        ("Ctrl+C", "Quit the TUI (same as /exit)"),
        ("PageUp / PageDown", "Scroll the transcript"),
        ("↑ / ↓ at edge", "Scroll up/down when the cursor is at the input edge"),
    ]

    TIPS: list[tuple[str, str]] = [
        ("Slash commands", "Type / to browse commands, or /commands for the full list."),
        ("Skills", "Run /skills to see what the connected agent can do."),
        ("Paste images", "Paste a local image path; it attaches to your next message."),
        ("Resume a thread", "/resume opens a picker of recent threads."),
        ("Rewind to earlier", "/rewind branches a new thread from any past user turn."),
        ("Switch theme", "/theme lists themes; /theme <name> applies one."),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-root"):
            yield Static("", id="help-title")
            with VerticalScroll(id="help-body"):
                yield Static(self._section("Getting started"))
                yield Static(Text("Type a message and press Enter to chat with the agent.", style="dim"))
                yield Static(self._section("Keyboard shortcuts"))
                yield Static(self._table(self.SHORTCUTS))
                yield Static(self._section("Tips"))
                yield Static(self._table(self.TIPS))
            yield Static("Esc to close", id="help-footer")

    async def on_mount(self) -> None:
        body = self.query_one("#help-body", VerticalScroll)
        body.can_focus = False
        self.can_focus = True
        self.query_one("#help-title", Static).update(Text("Help", style="bold"))
        self.set_focus(None)

    async def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "ctrl+c", "q"):
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return
        if event.key in ("up", "k"):
            self.query_one("#help-body", VerticalScroll).scroll_up(animate=False)
            return
        if event.key in ("down", "j"):
            self.query_one("#help-body", VerticalScroll).scroll_down(animate=False)
            return
        if event.key == "pageup":
            self.query_one("#help-body", VerticalScroll).scroll_page_up(animate=False)
            return
        if event.key == "pagedown":
            self.query_one("#help-body", VerticalScroll).scroll_page_down(animate=False)
            return

    @staticmethod
    def _section(title: str) -> Text:
        return Text(title, style=f"bold {_theme.ACCENT_COLOR}")

    @staticmethod
    def _table(rows: list[tuple[str, str]]) -> Table:
        width = max(len(k) for k, _ in rows) + 1
        table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
        table.add_column("key", style=f"bold {_theme.ACCENT_COLOR}", min_width=width)
        table.add_column("desc", style="dim", overflow="fold")
        for key, desc in rows:
            table.add_row(key, desc)
        return table


class CommandsScreen(Screen[None]):
    """Full-screen list of available slash commands.

    Static content (no selection); dismissed with Esc / Ctrl+C / q.
    """

    DEFAULT_CSS = """
    CommandsScreen { background: $background; layout: vertical; }

    #commands-root { padding: 1 2; height: 1fr; background: $background; }

    #commands-title {
        height: auto;
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #commands-body {
        height: 1fr;
        background: $background;
        scrollbar-size: 0 0;
        padding: 0;
    }

    #commands-body Static {
        height: auto;
        background: $background;
        color: $text;
        padding: 0 0 1 0;
    }

    #commands-footer {
        height: auto;
        color: $text-muted;
        padding: 0;
    }
    """

    def __init__(self, builtins: dict[str, str]) -> None:
        super().__init__()
        self._builtins = builtins

    def compose(self) -> ComposeResult:
        with Vertical(id="commands-root"):
            yield Static("", id="commands-title")
            with VerticalScroll(id="commands-body"):
                if self._builtins:
                    yield Static(self._section("Built-in"))
                    yield Static(self._table(self._rows(self._builtins)))
                else:
                    yield Static(Text("No commands registered.", style="dim"))
                yield Static(self._section("Skills"))
                yield Static(self._skills_note())
            yield Static("Esc to close", id="commands-footer")

    async def on_mount(self) -> None:
        body = self.query_one("#commands-body", VerticalScroll)
        body.can_focus = False
        self.can_focus = True
        self.query_one("#commands-title", Static).update(Text("Commands", style="bold"))
        self.set_focus(None)

    async def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "ctrl+c", "q"):
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return
        if event.key in ("up", "k"):
            self.query_one("#commands-body", VerticalScroll).scroll_up(animate=False)
            return
        if event.key in ("down", "j"):
            self.query_one("#commands-body", VerticalScroll).scroll_down(animate=False)
            return
        if event.key == "pageup":
            self.query_one("#commands-body", VerticalScroll).scroll_page_up(animate=False)
            return
        if event.key == "pagedown":
            self.query_one("#commands-body", VerticalScroll).scroll_page_down(animate=False)
            return

    @staticmethod
    def _rows(cmds: dict[str, str]) -> list[tuple[str, str]]:
        return [(f"/{name}", desc or "—") for name, desc in sorted(cmds.items())]

    @staticmethod
    def _section(title: str) -> Text:
        return Text(title, style=f"bold {_theme.ACCENT_COLOR}")

    @staticmethod
    def _skills_note() -> Text:
        accent = _theme.current_theme().accent
        note = Text(style="dim")
        note.append(
            "Skills are agent-specific capabilities exposed by the connected server. "
            "Invoke one as "
        )
        note.append("/<skill-name>", style=f"bold {accent}")
        note.append(" (with optional arguments). Run ")
        note.append("/skills", style=f"bold {accent}")
        note.append(" to see what the current agent can do.")
        return note

    @staticmethod
    def _table(rows: list[tuple[str, str]]) -> Table:
        width = max(len(k) for k, _ in rows) + 1
        table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
        table.add_column("name", style=f"bold {_theme.ACCENT_COLOR}", min_width=width)
        table.add_column("desc", style="dim", overflow="fold")
        for key, desc in rows:
            table.add_row(key, desc)
        return table


class StatusScreen(Screen[None]):
    """Full-screen connection and session info.

    Static content (no selection); dismissed with Esc / Ctrl+C / q.
    """

    DEFAULT_CSS = """
    StatusScreen { background: $background; layout: vertical; }

    #status-root { padding: 1 2; height: 1fr; background: $background; }

    #status-title {
        height: auto;
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #status-body {
        height: 1fr;
        background: $background;
        scrollbar-size: 0 0;
        padding: 0;
    }

    #status-body Static {
        height: auto;
        background: $background;
        color: $text;
        padding: 0 0 1 0;
    }

    #status-footer {
        height: auto;
        color: $text-muted;
        padding: 0;
    }
    """

    def __init__(
        self,
        connection: list[tuple[str, str]],
        usage: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self._connection = connection
        self._usage = usage

    def compose(self) -> ComposeResult:
        with Vertical(id="status-root"):
            yield Static("", id="status-title")
            with VerticalScroll(id="status-body"):
                yield Static(self._section("Connection"))
                yield Static(self._table(self._connection))
                yield Static(self._section("Usage"))
                yield Static(self._table(self._usage))
            yield Static("Esc to close", id="status-footer")

    async def on_mount(self) -> None:
        body = self.query_one("#status-body", VerticalScroll)
        body.can_focus = False
        self.can_focus = True
        self.query_one("#status-title", Static).update(Text("Status", style="bold"))
        self.set_focus(None)

    async def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "ctrl+c", "q"):
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return
        if event.key in ("up", "k"):
            self.query_one("#status-body", VerticalScroll).scroll_up(animate=False)
            return
        if event.key in ("down", "j"):
            self.query_one("#status-body", VerticalScroll).scroll_down(animate=False)
            return
        if event.key == "pageup":
            self.query_one("#status-body", VerticalScroll).scroll_page_up(animate=False)
            return
        if event.key == "pagedown":
            self.query_one("#status-body", VerticalScroll).scroll_page_down(animate=False)
            return

    @staticmethod
    def _section(title: str) -> Text:
        return Text(title, style=f"bold {_theme.ACCENT_COLOR}")

    @staticmethod
    def _table(rows: list[tuple[str, str]]) -> Table:
        width = max(len(k) for k, _ in rows) + 1
        table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
        table.add_column("label", style=f"bold {_theme.ACCENT_COLOR}", min_width=width)
        table.add_column("value", style="dim", overflow="fold")
        for key, value in rows:
            table.add_row(key, value)
        return table


class SettingsScreen(ModalScreen[None]):
    """Three-tab settings view: Config (interactive), Harness (static),
    Status (static).

    Rendered as a bottom-anchored modal — the top of the underlying chat
    stays visible through a hazy ($surface @ 70%) screen background,
    while the panel docks to the lower 60% with a rounded border.

    Tabs are switched with Tab/Shift+Tab. On the Config tab, ↑/↓ move the
    highlighted row and ←/→ cycle its value; every change is persisted to
    `~/.deepagent-tui/config.toml` and applied to the live session. Esc /
    Ctrl+C / q dismisses the screen.
    """

    DEFAULT_CSS = """
    SettingsScreen { background: $surface 70%; }

    #settings-root {
        dock: bottom;
        padding: 1 2;
        height: 60%;
        background: $background;
        border: round #4b5563;
    }

    #settings-tabs {
        height: auto;
        padding: 0 0 1 0;
    }

    #settings-body {
        height: 1fr;
        background: $background;
        scrollbar-size: 0 0;
        padding: 0;
    }

    #settings-body Static {
        height: auto;
        background: $background;
        color: $text;
        padding: 0 0 1 0;
    }

    #settings-footer {
        height: auto;
        color: $text-muted;
        padding: 0;
    }
    """

    TABS: tuple[str, ...] = ("Config", "Harness", "Status")

    def __init__(self, session: Any) -> None:
        super().__init__()
        self._session = session
        self._active_tab: int = 0
        self._selected_row: int = 0

    def _next_tab(self) -> None:
        self._active_tab = (self._active_tab + 1) % len(self.TABS)
        self._selected_row = 0
        self._refresh_all()

    def _prev_tab(self) -> None:
        self._active_tab = (self._active_tab - 1) % len(self.TABS)
        self._selected_row = 0
        self._refresh_all()

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-root"):
            yield Static("", id="settings-tabs")
            with VerticalScroll(id="settings-body"):
                yield Static("", id="settings-content")
            yield Static("", id="settings-footer")

    async def on_mount(self) -> None:
        body = self.query_one("#settings-body", VerticalScroll)
        body.can_focus = False
        self.can_focus = True
        self._refresh_all()
        self.set_focus(None)

    async def on_key(self, event: events.Key) -> None:
        key = event.key
        if key in ("escape", "ctrl+c", "q"):
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return

        # Tab cycling. Tab itself is claimed by the app's autocomplete
        # priority binding, so we use ] / [ (next/prev) — and accept
        # tab / shift+tab as aliases for users whose terminals route them
        # through to the screen anyway.
        if key in ("]", "tab"):
            event.stop()
            event.prevent_default()
            self._next_tab()
            return
        if key in ("[", "shift+tab"):
            event.stop()
            event.prevent_default()
            self._prev_tab()
            return

        # Config-tab-only interaction.
        if self._active_tab != 0:
            return

        rows = self._config_rows()
        if not rows:
            return

        if key in ("up", "k"):
            event.stop()
            event.prevent_default()
            self._selected_row = (self._selected_row - 1) % len(rows)
            self._refresh_body()
            return
        if key in ("down", "j"):
            event.stop()
            event.prevent_default()
            self._selected_row = (self._selected_row + 1) % len(rows)
            self._refresh_body()
            return
        if key in ("left", "h"):
            event.stop()
            event.prevent_default()
            self._cycle_current(-1)
            return
        if key in ("right", "l", "space"):
            event.stop()
            event.prevent_default()
            self._cycle_current(+1)
            return

    # ── rendering ──────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        self._refresh_tabs()
        self._refresh_body()
        self._refresh_footer()

    def _refresh_tabs(self) -> None:
        accent = _theme.current_theme().accent
        line = Text()
        for i, name in enumerate(self.TABS):
            if i:
                line.append("   ", style="dim")
            if i == self._active_tab:
                line.append(f" {name} ", style=f"bold reverse {accent}")
            else:
                line.append(f" {name} ", style="dim")
        self.query_one("#settings-tabs", Static).update(line)

    def _refresh_body(self) -> None:
        content = self.query_one("#settings-content", Static)
        if self._active_tab == 0:
            content.update(self._render_config())
        elif self._active_tab == 1:
            content.update(self._render_harness())
        else:
            content.update(self._render_status())

    def _refresh_footer(self) -> None:
        if self._active_tab == 0:
            hint = "↑↓ select  ·  ←→ change  ·  [ ] switch tab  ·  Esc close"
        else:
            hint = "[ ] switch tab  ·  Esc close"
        self.query_one("#settings-footer", Static).update(hint)

    # ── config tab ─────────────────────────────────────────────────────────

    def _config_rows(self) -> list[tuple[str, str]]:
        from deepagent_tui.ui.theme import current_theme

        return [
            ("HITL", "on" if self._session.hitl_enabled else "off"),
            ("Tool widgets", self._session.tool_widget_mode),
            ("Theme", current_theme().name),
        ]

    def _render_config(self) -> RenderableType:
        rows = self._config_rows()
        accent = _theme.current_theme().accent
        label_width = max(len(label) for label, _ in rows) + 2
        out = Text()
        for i, (label, value) in enumerate(rows):
            if i:
                out.append("\n")
            selected = i == self._selected_row
            if selected:
                out.append("❯ ", style=f"bold {accent}")
                out.append(label.ljust(label_width), style=f"bold {accent}")
                out.append(value, style=f"bold {accent}")
            else:
                out.append("  ")
                out.append(label.ljust(label_width), style="bold")
                out.append(value, style="dim")
        return out

    def _cycle_current(self, delta: int) -> None:
        from deepagent_tui.storage.config_store import UserConfig, save_config
        from deepagent_tui.ui.theme import (
            available_themes,
            current_theme,
            persist_theme,
            set_theme,
        )

        idx = self._selected_row
        if idx == 0:
            self._session.hitl_enabled = not self._session.hitl_enabled
            save_config(
                UserConfig(
                    hitl_enabled=self._session.hitl_enabled,
                    tool_widget_mode=self._session.tool_widget_mode,  # type: ignore[arg-type]
                )
            )
        elif idx == 1:
            modes = ("compacted", "default", "expanded")
            current = self._session.tool_widget_mode
            try:
                pos = modes.index(current)
            except ValueError:
                pos = 1  # unknown → land on "default"
            new_mode = modes[(pos + delta) % len(modes)]
            self._session.tool_widget_mode = new_mode
            # Mirror into the tool_widgets module so future renderers honor it.
            from deepagent_tui.ui.tool_widgets import set_widget_mode

            set_widget_mode(new_mode)
            # Re-render existing tool widgets so the toggle applies
            # retroactively to the whole transcript.
            if self._session.rerender_tool_widgets is not None:
                self._session.rerender_tool_widgets()
            save_config(
                UserConfig(
                    hitl_enabled=self._session.hitl_enabled,
                    tool_widget_mode=new_mode,  # type: ignore[arg-type]
                )
            )
        elif idx == 2:
            names = available_themes()
            try:
                pos = names.index(current_theme().name)
            except ValueError:
                pos = 0
            new_name = names[(pos + delta) % len(names)]
            set_theme(new_name)
            persist_theme(new_name)

        self._refresh_tabs()
        self._refresh_body()

    # ── harness tab ────────────────────────────────────────────────────────

    def _render_harness(self) -> RenderableType:
        rows = [
            ("Model", self._session.model or "unknown"),
            ("Skills", "Run /skills to see available capabilities"),
        ]
        return _static_table(rows)

    # ── status tab ─────────────────────────────────────────────────────────

    def _render_status(self) -> RenderableType:
        from deepagent_tui.config import settings as _settings
        from deepagent_tui.utils.cost import format_cost, format_tokens

        s = self._session
        rows = [
            ("Server", _settings.langgraph_url),
            ("Graph", s.graph_id or "not connected"),
            ("Assistant", s.assistant_id or "not connected"),
            ("Thread", s.thread_id or "none"),
            ("Model", s.model or "unknown"),
            ("Status", s.status),
            (
                "Tokens",
                f"{format_tokens(s.input_tokens)} in / {format_tokens(s.output_tokens)} out",
            ),
            ("Cost", format_cost(s.total_cost)),
        ]
        return _static_table(rows)


def _static_table(rows: list[tuple[str, str]]) -> Table:
    """Two-column key/value table shared by the static settings tabs."""
    width = max(len(k) for k, _ in rows) + 1
    table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
    table.add_column("label", style=f"bold {_theme.ACCENT_COLOR}", min_width=width)
    table.add_column("value", style="dim", overflow="fold")
    for key, value in rows:
        table.add_row(key, value)
    return table
