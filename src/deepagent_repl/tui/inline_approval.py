from __future__ import annotations

import asyncio
from os.path import basename
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

import deepagent_repl.ui.theme as _theme
from deepagent_repl.handlers.interrupt import InterruptInfo


_OPTION_LABELS: dict[str, str] = {
    "approve": "Yes",
    "accept": "Yes",
    "yes": "Yes",
    "reject": "No",
    "deny": "No",
    "no": "No",
}

# Decisions we don't surface in the inline UI. `edit` would need an editor
# round-trip to collect the revised payload — without that, picking it just
# silently degrades to approve, so we drop it from the list entirely.
_HIDDEN_OPTIONS = {"edit"}


def _friendly_options(interrupt: InterruptInfo) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in interrupt.options:
        if raw.lower() in _HIDDEN_OPTIONS:
            continue
        label = _OPTION_LABELS.get(raw.lower(), raw.replace("_", " ").capitalize())
        out.append((raw, label))
    return out


def _interrupt_args(interrupt: InterruptInfo) -> dict:
    """Merged args from action_requests, with single-action fallback."""
    out: dict = {}
    if isinstance(interrupt.value, dict):
        for ar in interrupt.value.get("action_requests", []):
            if isinstance(ar.get("args"), dict):
                out.update(ar["args"])
        if not out and isinstance(interrupt.value.get("args"), dict):
            out = dict(interrupt.value["args"])
    return out


class InlineApproval(Container):
    """Inline HITL approval widget — Claude Code-style numbered options.

    Mounted into the message stream so the prompt sits at the bottom of the
    transcript rather than in a centered modal. Captures keys directly:
    digits select+confirm, ↑/↓ navigate, Enter confirms, Esc/Ctrl+C cancels.
    Resolves the supplied future with the chosen raw option string, or None
    on cancel.
    """

    DEFAULT_CSS = """
    InlineApproval {
        height: auto;
        padding: 0;
        margin: 1 0 0 0;
        background: $background;
    }
    InlineApproval > #approval-body {
        height: auto;
        background: $background;
    }
    """

    can_focus = True

    def __init__(
        self,
        interrupt: InterruptInfo,
        future: asyncio.Future,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._interrupt = interrupt
        self._future = future
        self._options = _friendly_options(interrupt)
        self._selected = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="approval-body")

    def on_mount(self) -> None:
        self._refresh()
        self.focus()

    # ── rendering ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        # NB: avoid the name `_render` — that's a Textual Widget internal,
        # overriding it makes the framework try to render this Container's
        # Group directly and blow up with "Group has no attribute
        # render_strips".
        self.query_one("#approval-body", Static).update(self._build_view())

    def _title(self) -> str:
        if self._interrupt.description == "edit_file":
            fp = str(_interrupt_args(self._interrupt).get("file_path", "") or "")
            if fp:
                return f"Do you want to make this edit to {basename(fp)}?"
            return "Do you want to make this edit?"
        if self._interrupt.description:
            return f"Do you want to proceed with {self._interrupt.description}?"
        return "Do you want to proceed?"

    def _build_view(self) -> RenderableType:
        accent = _theme.current_theme().accent
        lines: list[Text] = [Text(self._title(), style="bold")]
        for i, (_raw, label) in enumerate(self._options):
            if i == self._selected:
                line = Text()
                line.append("❯ ", style=f"bold {accent}")
                line.append(f"{i + 1}. {label}", style=f"bold {accent}")
            else:
                line = Text(f"  {i + 1}. {label}")
            lines.append(line)
        lines.append(Text(""))
        lines.append(
            Text("Esc to cancel  ·  ↑/↓ to navigate  ·  Enter to confirm", style="dim")
        )
        return Group(*lines)

    # ── input ─────────────────────────────────────────────────────────────

    async def on_key(self, event: events.Key) -> None:
        if self._future.done():
            return
        k = event.key
        if k in ("escape", "ctrl+c"):
            event.stop()
            event.prevent_default()
            self._future.set_result(None)
            return
        if k in ("up", "ctrl+p", "shift+tab"):
            event.stop()
            event.prevent_default()
            self._move(-1)
            return
        if k in ("down", "ctrl+n", "tab"):
            event.stop()
            event.prevent_default()
            self._move(+1)
            return
        if k == "enter":
            event.stop()
            event.prevent_default()
            self._confirm()
            return
        ch = event.character
        if ch and ch.isdigit():
            idx = int(ch) - 1
            if 0 <= idx < len(self._options):
                event.stop()
                event.prevent_default()
                self._selected = idx
                self._confirm()
                return

    def _move(self, delta: int) -> None:
        if not self._options:
            return
        self._selected = (self._selected + delta) % len(self._options)
        self._refresh()

    def _confirm(self) -> None:
        if self._options and not self._future.done():
            raw, _label = self._options[self._selected]
            self._future.set_result(raw)

