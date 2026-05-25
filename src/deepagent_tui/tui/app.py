from __future__ import annotations

import io
import os
import time
import traceback
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.console import RenderableType
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Rule, Static, TextArea
from textual.widgets import OptionList
from textual.widgets.option_list import Option

import deepagent_tui.ui.theme as _theme
from deepagent_tui.client import AgentClient
from deepagent_tui.config import settings
from deepagent_tui.handlers.interrupt import (
    InterruptInfo,
    build_resume_value,
    extract_interrupts,
)
from deepagent_tui.handlers.stream import (
    StreamState,
    process_messages_event,
    process_updates_event,
)
from deepagent_tui.handlers.tools import (
    FormattedToolCall,
    FormattedToolResult,
    format_tool_call,
    format_tool_result,
)
from deepagent_tui.session import Session
from deepagent_tui.storage.db import upsert_thread
from deepagent_tui.tui.inline_approval import InlineApproval
from deepagent_tui.tui.screens import (
    CommandsScreen,
    HelpScreen,
    PickerItem,
    PickerScreen,
    StatusScreen,
)
from deepagent_tui.ui.markdown import render_markdown

_DEBUG = os.environ.get("DEEPAGENT_DEBUG") == "1"


def _command_color() -> str:
    """Hex color used for slash/question hints and autocomplete entries."""
    return _theme.current_theme().command


def _user_message_text(text: str) -> Text:
    """Render a submitted message. If it starts with a slash command, paint
    the `/name` token in the command accent color so it stands out from the
    rest of the user message. Subsequent lines are indented to align past
    the leading `❯ ` prefix."""
    indent = "\n  "
    accent = _theme.ACCENT_COLOR
    out = Text()
    out.append("❯ ", style=accent)
    if text.startswith("/"):
        head, sep, tail = text.partition(" ")
        out.append(head.replace("\n", indent), style=_command_color())
        if sep:
            out.append((sep + tail).replace("\n", indent))
        return out
    out.append(text.replace("\n", indent))
    return out


def _user_message_with_attachments(
    text: str, image_paths: list[str]
) -> RenderableType:
    """User message header followed by dim lines listing attached images."""
    header = _user_message_text(text)
    if not image_paths:
        return header
    rows: list[RenderableType] = [header]
    accent = _theme.ACCENT_COLOR
    for p in image_paths:
        rows.append(Text(f"  + {Path(p).name}", style=f"dim {accent}"))
    return Group(*rows)


def _user_message_widget(content: RenderableType, *, multiline: bool) -> Static:
    """Static wrapper for a user message. Multi-line bubbles get a left
    vertical bar in the theme accent color; single-line ones stay bare so
    the `❯` prefix carries the emphasis on its own."""
    widget = Static(content, classes="msg-user")
    if multiline:
        widget.styles.border_left = ("solid", _theme.ACCENT_COLOR)
    return widget


class StatusBar(Static):
    """Single-line bottom status bar that updates from session state."""

    def __init__(self, session: Session, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._session = session

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        from deepagent_tui.utils.cost import format_cost, format_tokens

        s = self._session
        model = s.model or "—"
        toks = f"{format_tokens(s.input_tokens)}↑ {format_tokens(s.output_tokens)}↓"
        cost = format_cost(s.total_cost)
        status_tag = f" [{s.status}]" if s.status != "idle" else ""
        self.update(
            f" {model} │ {toks} │ {cost}{status_tag}"
        )


class HintBar(Static):
    """Single-row bar below the chat input. Renders the per-turn wall
    clock (⏱  mm:ss) followed by a context-aware hint: actionable cues
    while streaming or composing, otherwise rotating between the
    workspace path and tips."""

    _TIPS = (
        "Pass images with ⌘C / ⌘V.",
    )
    _TICK = 0.1
    _ROTATE_EVERY = 100  # 0.1s * 100 = 10s between idle rotations

    def __init__(self, session: Session, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._session = session
        self._tick = 0
        self._timer_start: float | None = None
        self._last_elapsed: float | None = None

    def on_mount(self) -> None:
        self.set_interval(self._TICK, self._refresh)
        self._refresh()

    def begin_timer(self) -> None:
        self._timer_start = time.monotonic()
        self._last_elapsed = None
        self._refresh()

    def end_timer(self) -> None:
        if self._timer_start is not None:
            self._last_elapsed = time.monotonic() - self._timer_start
        self._timer_start = None
        self._refresh()

    def reset_timer(self) -> None:
        self._timer_start = None
        self._last_elapsed = None
        self._refresh()

    def _refresh(self) -> None:
        self._tick += 1
        self.update(self._compose_row())

    def _compose_row(self) -> Text:
        row = Text("  ", style="dim")
        clock = self._clock_text()
        if clock is not None:
            row.append(clock, style="dim")
            row.append("   ·  ", style="dim")
        row.append(self._hint_text(), style="dim")
        return row

    def _clock_text(self) -> str | None:
        if self._timer_start is not None:
            return f"⏱  {self._format_elapsed(time.monotonic() - self._timer_start)}"
        if self._last_elapsed is not None:
            return f"⏱  {self._format_elapsed(self._last_elapsed)}"
        return None

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 60:02d}:{total % 60:02d}"

    def _hint_text(self) -> str:
        s = self._session
        if s.status == "streaming":
            return "ESC to interrupt"
        if s.status == "interrupted":
            return "awaiting approval — use the buttons above"

        try:
            value = self.app.query_one("#prompt", ChatTextArea).text
        except Exception:
            value = ""

        if value.startswith("/"):
            return "Tab to complete · Enter to run"
        if value.strip():
            return "Enter to send · Shift+Enter for newline"

        options: list[str] = []
        ws = _workspace_label(s)
        if ws:
            options.append(ws)
        options.extend(self._TIPS)
        idx = (self._tick // self._ROTATE_EVERY) % len(options)
        return options[idx]


class WelcomeBanner(Static):
    """Top banner: ASCII graph name, workspace · thread, /commands. Scrolls with content."""

    def __init__(self, session: Session, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._session = session
        self._connecting_to: str | None = None

    def on_mount(self) -> None:
        self.refresh_content()

    def set_connecting(self, url: str | None) -> None:
        self._connecting_to = url
        self.refresh_content()

    def refresh_content(self) -> None:
        from pyfiglet import Figlet

        graph = (self._session.graph_id or "deepagent").strip()
        try:
            art = Figlet(font="ansi_shadow", width=200).renderText(f"> {graph}").rstrip("\n")
        except Exception:
            art = f"> {graph}"

        lines = [ln for ln in art.split("\n") if ln.rstrip()]
        max_w = max((len(ln) for ln in lines), default=1)

        rows: list[Any] = []
        if self._connecting_to:
            rows.append(Text(f"Connecting to {self._connecting_to}…", style="dim"))
            rows.append(Text(""))
        for line in lines:
            rows.append(_gradient_line(line, max_w))

        sep = Text("  ◆  ", style="dim")
        cmd = _command_color()
        rows.append(Text(""))
        rows.append(
            Text.assemble(
                ("/", f"bold {cmd}"),
                (" for commands", "dim"),
                sep,
                ("?", f"bold {cmd}"),
                (" for shortcuts", "dim"),
            )
        )

        self.update(Group(*rows))


_THINKING_FRAMES = ["⠋", "⠙", "⠚", "⠞", "⠖", "⠦", "⠴", "⠲", "⠳", "⠓"]


def _thinking_renderable(frame: int) -> Text:
    spinner = _THINKING_FRAMES[frame % len(_THINKING_FRAMES)]
    accent = _theme.ACCENT_COLOR
    return Text.assemble((spinner, f"bold {accent}"), ("  Thinking…", "dim"))


class ChatTextArea(TextArea):
    """Multi-line chat input. Enter submits, Shift/Alt+Enter or Ctrl+J newline."""

    class Submitted(Message):
        """Posted when the user presses Enter to send the current buffer."""

        def __init__(self, text_area: "ChatTextArea", value: str) -> None:
            super().__init__()
            self.text_area = text_area
            self.value = value

        @property
        def control(self) -> "ChatTextArea":
            return self.text_area

    class AttachmentsPasted(Message):
        """Posted when a paste contains one or more image paths."""

        def __init__(self, text_area: "ChatTextArea", paths: list[str]) -> None:
            super().__init__()
            self.text_area = text_area
            self.paths = paths

        @property
        def control(self) -> "ChatTextArea":
            return self.text_area

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        if key in ("shift+enter", "alt+enter", "ctrl+j"):
            event.stop()
            event.prevent_default()
            self.insert("\n", maintain_selection_offset=False)
            return
        if key in ("up", "down"):
            # While the autocomplete menu is showing, leave arrows alone so the
            # user can keep editing the slash command without scrolling history.
            try:
                ac = self.app.query_one("#autocomplete", OptionList)
                ac_visible = "-hidden" not in ac.classes
            except Exception:
                ac_visible = False
            if not ac_visible:
                row, _ = self.cursor_location
                last_row = self.document.line_count - 1
                at_edge = (key == "up" and row == 0) or (
                    key == "down" and row == last_row
                )
                if at_edge:
                    event.stop()
                    event.prevent_default()
                    try:
                        scroll = self.app.query_one("#main", VerticalScroll)
                    except Exception:
                        return
                    if key == "up":
                        scroll.scroll_up(animate=False)
                    else:
                        scroll.scroll_down(animate=False)
                    return
        await super()._on_key(event)

    async def _on_paste(self, event: events.Paste) -> None:
        from deepagent_tui.utils.images import extract_image_paths

        cleaned, paths = extract_image_paths(event.text)
        if paths:
            event.stop()
            event.prevent_default()
            self.post_message(self.AttachmentsPasted(self, paths))
            if cleaned:
                self.insert(cleaned, maintain_selection_offset=False)
            return
        await super()._on_paste(event)


class ChatBar(Container):
    """Multi-line chat input box with a leading ❯ symbol."""

    DEFAULT_CSS = ""  # styled via app CSS

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-bar-row"):
            yield Static("❯", id="chat-prompt-icon")
            yield ChatTextArea(
                id="prompt",
                placeholder="Type your message…",
                compact=True,
                highlight_cursor_line=False,
                soft_wrap=True,
            )


class DeepAgentTUI(App):
    """Textual front-end for the Deep Agent REPL."""

    CSS = """
    Screen {
        layout: vertical;
        background: $background;
        scrollbar-size: 0 0;
    }

    #main {
        height: 1fr;
        background: $background;
        padding: 0;
        scrollbar-size: 0 0;
        overflow-x: hidden;
        overflow-y: auto;
    }

    #welcome {
        height: auto;
        padding: 1 2 0 2;
        background: $background;
    }

    #messages {
        height: auto;
        padding: 0 2;
        background: $background;
    }

    #messages .msg {
        height: auto;
        padding: 0;
        margin: 1 0 0 0;
        background: $background;
        color: $text;
    }

    #messages .msg-user {
        height: auto;
        padding: 0 0 0 1;
        margin: 1 0 0 0;
        background: $background;
        color: $text;
    }

    /* Slash-command output (render_info / render_error / render_renderable).
       Margin 0 so the `⎿` body sits flush under the user's `❯ /command`
       submission and consecutive command lines stack tight together. */
    #messages .msg-cmd {
        height: auto;
        padding: 0;
        margin: 0;
        background: $background;
        color: $text;
    }

    #autocomplete {
        height: auto;
        max-height: 10;
        padding: 0 2;
        background: $background;
        border: none;
        scrollbar-size: 0 0;
    }
    #autocomplete.-hidden { display: none; }

    #attachments {
        height: auto;
        padding: 0 2;
        background: $background;
        color: $text;
    }
    #attachments.-hidden { display: none; }

    #chat-rule-top {
        height: 1;
        color: #4b5563;
        background: $background;
        padding: 0;
        margin: 1 0 0 0;
    }
    #chat-rule-bottom {
        height: 1;
        color: #4b5563;
        background: $background;
        padding: 0;
        margin: 0;
    }

    #hint-bar {
        height: 1;
        padding: 0 2;
        background: $background;
        color: $text-muted;
    }

    ChatBar {
        height: auto;
        max-height: 12;
        border: none;
        background: $background;
        padding: 0 2;
    }

    #chat-bar-row {
        height: auto;
        max-height: 12;
        background: $background;
    }

    #chat-prompt-icon {
        width: 2;
        height: 1;
        color: #6b7280;
        text-style: bold;
        background: $background;
        padding: 0;
        margin: 0 1 0 0;
    }

    #prompt {
        border: none;
        background: $background;
        color: #9ca3af;
        padding: 0;
        height: auto;
        min-height: 1;
        max-height: 10;
        scrollbar-size: 0 0;
    }
    #prompt:focus {
        border: none;
        background: $background;
    }
    #prompt .text-area--cursor-line {
        background: $background;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $background;
        color: $text-muted;
    }

    /* Hide chat input + rules while an inline approval is waiting so the
       hint line ("Esc to cancel · …") becomes the last visible row, matching
       Claude Code's bottom-of-transcript prompt. The class is toggled on
       each widget directly in `_set_approval_active`. */
    .-approval-hidden { display: none; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
        Binding("escape", "hide_autocomplete", "Hide autocomplete", show=False),
        Binding("tab", "complete_command", "Complete", show=False, priority=True),
        Binding("pageup", "scroll_history_up", "Scroll up", show=False, priority=True),
        Binding("pagedown", "scroll_history_down", "Scroll down", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client = AgentClient(
            url=settings.langgraph_url, api_key=settings.langsmith_api_key
        )
        self.session = Session()
        self._stream_buffer: str = ""
        self._active_slot: Static | None = None
        self._thinking_timer = None
        self._thinking_frame: int = 0
        self._pending_attachments: list[str] = []
        # Pending tool calls awaiting their result. Keyed by tool_call_id so the
        # marker on the call widget can be flipped from ○ pending → ● green/red
        # once the corresponding tool message arrives.
        self._tool_widgets: dict[str, tuple[Static, FormattedToolCall]] = {}
        # Subagent (task) bookkeeping. `_subagent_progress` holds the running
        # list of `⎿ tool` lines per task call_id. `_subagent_ns_to_id` maps a
        # stream-subgraph namespace ("tools:<checkpoint_id>") to the task
        # call_id whose inner activity it represents — bound lazily the first
        # time we see events for a new namespace, popping the oldest pending
        # task call (FIFO matches sequential subagent dispatch).
        self._subagent_progress: dict[str, list[tuple[str, str]]] = {}
        self._subagent_ns_to_id: dict[str, str] = {}
        self._pending_subagent_ids: list[str] = []
        # ESC-rollback bookkeeping: capture the in-flight turn so ESC during
        # streaming can drop the user message and restore it to the input bar.
        self._stream_worker = None
        self._active_run_id: str | None = None
        self._turn_start_index: int | None = None
        self._last_user_text: str = ""
        self._last_user_attachments: list[str] = []
        self._cancelling: bool = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="main"):
            yield WelcomeBanner(self.session, id="welcome")
            yield Container(id="messages")
            yield Rule(line_style="solid", id="chat-rule-top")
            yield Static("", id="attachments", classes="-hidden")
            yield ChatBar(id="chat-bar")
            yield Rule(line_style="solid", id="chat-rule-bottom")
            yield HintBar(self.session, id="hint-bar")
            yield OptionList(id="autocomplete", classes="-hidden")
        yield StatusBar(self.session, id="status-bar")

    async def on_mount(self) -> None:
        self.session.picker = self._tui_pick
        self.session.replay = self._replay_thread
        self.session.show_help = self._tui_show_help
        self.session.show_commands = self._tui_show_commands
        self.session.show_status = self._tui_show_status
        self.session.set_input = self._tui_set_input
        # Route render_info / render_error / render_renderable straight into
        # the message log so each call becomes ONE widget — the multi-line
        # `⎿` corner format depends on staying inside a single Static.
        from deepagent_tui.ui.renderer import set_mount_sink
        set_mount_sink(self._write_cmd_renderable)
        welcome = self.query_one("#welcome", WelcomeBanner)
        welcome.set_connecting(settings.langgraph_url)

        from deepagent_tui.bootstrap import connect, discover_and_register_skills

        with _capture_console() as cap:
            try:
                ok = await connect(self.client, self.session)
            except Exception as e:  # noqa: BLE001
                ok = False
                self._write_text(f"  Connection error: {e}", style="bold red")
                if _DEBUG:
                    self._write_text(traceback.format_exc(), style="red")
        self._flush_capture(cap)

        if not ok:
            self._write_text("  Failed to connect — exiting in 3s.", style="bold red")
            self.set_timer(3.0, self.exit)
            return

        with _capture_console() as cap:
            try:
                await discover_and_register_skills(self.client, self.session)
            except Exception as e:  # noqa: BLE001
                self._write_text(f"  Skill discovery skipped: {e}", style="dim red")
        self._flush_capture(cap)

        welcome.set_connecting(None)
        self.query_one("#prompt", ChatTextArea).focus()

    # ── Input / autocomplete ────────────────────────────────────────────────

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        self._refresh_autocomplete(event.text_area.text)

    def _refresh_autocomplete(self, value: str) -> None:
        ac = self.query_one("#autocomplete", OptionList)
        # Slash-command autocomplete is single-line by nature; hide if the
        # user has started a multi-line message.
        if not value.startswith("/") or "\n" in value:
            was_visible = "-hidden" not in ac.classes
            ac.add_class("-hidden")
            ac.clear_options()
            if was_visible:
                self._scroll_to_input()
            return

        from deepagent_tui.commands import all_commands

        prefix = value[1:].split(None, 1)[0] if len(value) > 1 else ""
        prefix_lc = prefix.lower()
        matches = sorted(
            (name, desc)
            for name, desc in all_commands().items()
            if name.lower().startswith(prefix_lc)
        )
        ac.clear_options()
        if not matches:
            was_visible = "-hidden" not in ac.classes
            ac.add_class("-hidden")
            if was_visible:
                self._scroll_to_input()
            return

        name_width = max(len(n) for n, _ in matches) + 2
        cmd = _command_color()
        for name, desc in matches[:20]:
            padded = f"/{name}".ljust(name_width)
            label = Text.assemble(
                (padded, f"bold {cmd}"),
                ("  ", ""),
                (desc or "", "dim"),
            )
            ac.add_option(Option(label, id=name))
        ac.remove_class("-hidden")
        ac.refresh(layout=True)
        self._scroll_to_input()

    def action_hide_autocomplete(self) -> None:
        # While an inline approval is up, Esc cancels the approval (the
        # widget owns the key — but App `priority=True` bindings fire first,
        # so we have to forward here).
        if self.screen.has_class("-approval-active"):
            try:
                approval = self.query_one(InlineApproval)
                if not approval._future.done():
                    approval._future.set_result(None)
            except Exception:
                pass
            return
        # ESC during a model stream interrupts the run, drops the in-flight
        # user turn, and restores the typed message into the input bar so the
        # user can edit and resend. Takes precedence over the autocomplete /
        # attachments behaviors below.
        if (
            self.session.status == "streaming"
            and self._stream_worker is not None
            and not self._cancelling
        ):
            self.run_worker(
                self._cancel_and_rollback(),
                exclusive=False,
                name="cancel-rollback",
            )
            return

        ac = self.query_one("#autocomplete", OptionList)
        ac_was_visible = "-hidden" not in ac.classes
        ac.add_class("-hidden")
        ac.clear_options()
        # Esc with autocomplete closed clears any pending attachments — first
        # Esc dismisses the menu, second Esc drops the staged images.
        if not ac_was_visible and self._pending_attachments:
            self._pending_attachments.clear()
            self._refresh_attachments_preview()
        self._scroll_to_input()

    async def _cancel_and_rollback(self) -> None:
        """Stop the in-flight run, remove its UI traces, and put the user's
        message back in the input bar for editing."""
        self._cancelling = True
        try:
            run_id = self._active_run_id
            thread_id = self.session.thread_id
            worker = self._stream_worker
            saved_text = self._last_user_text
            saved_attachments = list(self._last_user_attachments)
            start_idx = self._turn_start_index

            # Ask the server to roll the run back. Fire-and-forget — we don't
            # want to block the UI on a network round-trip, and the local
            # rollback is what the user actually sees.
            if run_id and thread_id:
                async def _server_rollback() -> None:
                    try:
                        await self.client._client.runs.cancel(
                            thread_id, run_id, action="rollback", wait=False,
                        )
                    except Exception:
                        pass
                self.run_worker(
                    _server_rollback(), exclusive=False, name="server-rollback"
                )

            # Cancel the local stream worker — raises CancelledError inside
            # _consume_stream on its next await, which unwinds _submit_message.
            if worker is not None:
                try:
                    worker.cancel()
                except Exception:
                    pass

            # Tear down everything mounted during this turn: user bubble, any
            # tool-call / tool-result panels, partial assistant markdown, the
            # active thinking slot. Clear _active_slot before removal so the
            # worker's finally doesn't try to remove an already-detached widget.
            self._stop_thinking_timer()
            self._active_slot = None
            if start_idx is not None:
                for child in list(self._messages.children[start_idx:]):
                    try:
                        child.remove()
                    except Exception:
                        pass

            # Drop the user turn from local session history.
            if (
                self.session.messages
                and self.session.messages[-1].get("role") == "user"
            ):
                self.session.messages.pop()

            # Restore the input bar (replace whatever the user may have typed
            # while waiting — matches the explicit "Replace with restored
            # message" preference).
            prompt = self.query_one("#prompt", ChatTextArea)
            prompt.text = saved_text
            prompt.move_cursor(prompt.document.end)
            self._pending_attachments = saved_attachments
            self._refresh_attachments_preview()

            self.session.status = "idle"
            self._stream_buffer = ""
            self._active_run_id = None
            self._stream_worker = None
            self._turn_start_index = None
            self._last_user_text = ""
            self._last_user_attachments = []
            prompt.focus()
            self._scroll_to_input()
        finally:
            self._cancelling = False

    def action_complete_command(self) -> None:
        # While an inline approval is up, Tab navigates the option list
        # rather than completing a slash-command.
        if self.screen.has_class("-approval-active"):
            try:
                approval = self.query_one(InlineApproval)
                approval._move(+1)
            except Exception:
                pass
            return
        ac = self.query_one("#autocomplete", OptionList)
        if "-hidden" in ac.classes:
            return
        if ac.option_count == 0:
            return
        first = ac.get_option_at_index(0)
        if first.id is None:
            return
        self._set_prompt_text(f"/{first.id} ")
        self.action_hide_autocomplete()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        # Only the autocomplete OptionList lives in the main app.
        if event.option_list.id != "autocomplete":
            return
        if event.option_id is None:
            return
        prompt = self._set_prompt_text(f"/{event.option_id} ")
        self.action_hide_autocomplete()
        prompt.focus()

    def _set_prompt_text(self, text: str) -> "ChatTextArea":
        prompt = self.query_one("#prompt", ChatTextArea)
        prompt.text = text
        prompt.move_cursor(prompt.document.end)
        return prompt

    # ── Submit / commands ───────────────────────────────────────────────────

    async def on_chat_text_area_submitted(
        self, message: ChatTextArea.Submitted
    ) -> None:
        raw_value = message.value
        text = raw_value.strip()
        pending = list(self._pending_attachments)
        if not text and not pending:
            return
        message.text_area.text = ""
        if self._pending_attachments:
            self._pending_attachments.clear()
            self._refresh_attachments_preview()
        self.action_hide_autocomplete()

        from deepagent_tui.commands import is_command

        image_paths: list[str] = []
        if not is_command(text):
            from deepagent_tui.utils.images import extract_image_paths

            cleaned, paths = extract_image_paths(text)
            image_paths = pending + paths
            if image_paths:
                text = cleaned or "Please analyze this image."

        # Mark the start of this turn so ESC-rollback can remove every widget
        # mounted after this point (user bubble, tool call panels, tool
        # results, partial assistant markdown, the active thinking slot).
        if not is_command(text):
            self._turn_start_index = len(self._messages.children)
        widget = _user_message_widget(
            _user_message_with_attachments(text, image_paths),
            multiline="\n" in text or bool(image_paths),
        )
        self._messages.mount(widget)
        self._scroll_to_input()

        if is_command(text):
            # Commands run in a worker so they can await modal screens
            # (push_screen_wait) without blocking the input widget's
            # message pump — that's what froze /resume's picker before.
            worker = self.run_worker(
                self._run_command(text),
                exclusive=True,
                name="command",
                exit_on_error=False,
            )
            self._track_worker(worker)
            return

        self._begin_turn_timer()

        if _DEBUG:
            self._write_text("  [debug] scheduling stream worker", style="dim yellow")

        if image_paths:
            from deepagent_tui.utils.images import build_multimodal_content

            content: str | list = build_multimodal_content(text, image_paths)
        else:
            content = text

        # Snapshot the turn so ESC can roll it back. Stash the raw input
        # (with any newlines the user typed), not the stripped/cleaned
        # version, so restoring the input bar feels like a true undo.
        self._last_user_text = raw_value
        self._last_user_attachments = list(pending)
        self._active_run_id = None

        worker = self.run_worker(
            self._submit_message(content),
            exclusive=True,
            name="stream",
            exit_on_error=False,
        )
        self._stream_worker = worker
        self._track_worker(worker)

    def _track_worker(self, worker) -> None:
        async def _watch() -> None:
            # worker.wait() raises WorkerCancelled when the tracked worker was
            # cancelled (e.g. ESC during streaming). Treat that as expected
            # rather than letting it tear down the watcher with an unhandled
            # exception screen.
            from textual.worker import WorkerCancelled

            try:
                await worker.wait()
            except WorkerCancelled:
                return
            err = getattr(worker, "error", None)
            if err is not None:
                self._write_text(f"  Worker failed: {err!r}", style="bold red")
                if _DEBUG:
                    import traceback as _tb
                    tb_str = "".join(_tb.format_exception(type(err), err, err.__traceback__))
                    self._write_text(tb_str, style="red")

        self.run_worker(_watch(), exclusive=False, name="worker-watch")

    async def _run_command(self, text: str) -> None:
        from deepagent_tui.commands import (
            dispatch as dispatch_command,
            get_command,
            is_dynamic,
        )

        self._reset_turn_timer()

        parts = text[1:].split(None, 1)
        name = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        name_lc = name.lower()

        # Dynamic skills delegate to _submit_message in a fresh worker —
        # that worker's finally block ends the turn timer. Every other
        # branch finishes here, so we end the timer ourselves on exit.
        end_timer_on_exit = True
        try:
            # /clear in TUI: clear the message log directly. The registered command
            # writes ANSI clear codes to the rich console, which the TUI captures
            # and discards — so the underlying command is a no-op here.
            if name_lc == "clear":
                self.action_clear_log()
                return

            # Dynamic (skill) commands: the registered handler streams via the
            # CLI's rich.live renderer, which the TUI's console capture buffers
            # until the whole turn finishes — producing a frozen UI and a burst
            # of "Thinking…" frames at the end. Route through the TUI-native
            # stream worker instead so output appears progressively.
            entry = get_command(name)
            if entry is not None and is_dynamic(name):
                # Use canonical (registered) name in the prompt so the agent sees
                # the skill name exactly as it was registered, even if the user
                # typed it in a different case.
                canonical = entry[2]
                prompt = f"Use the {canonical} skill"
                if args:
                    prompt += f": {args}"
                self._begin_turn_timer()
                worker = self.run_worker(
                    self._submit_message(prompt),
                    exclusive=True,
                    name="stream",
                    exit_on_error=False,
                )
                self._track_worker(worker)
                end_timer_on_exit = False
                return

            from deepagent_tui.ui.renderer import render_error

            with _capture_console() as cap:
                try:
                    handled = await dispatch_command(self.client, self.session, text)
                except Exception as e:  # noqa: BLE001
                    handled = True
                    render_error(f"Command error: {e}")
                    if _DEBUG:
                        self._write_text(traceback.format_exc(), style="red")

            # /new clears the previous conversation but should leave a visible
            # trace — `❯ /new` and the `⎿ New thread: <id>` acknowledgment that
            # cmd_new emitted. Keep just those last two widgets.
            if name_lc == "new" and handled:
                children = list(self._messages.children)
                for child in children[:-2]:
                    child.remove()
                self._tool_widgets.clear()

            # Repaint the welcome banner after any command: /theme changes the
            # gradient, and other commands may update session state shown there.
            try:
                self.query_one("#welcome", WelcomeBanner).refresh_content()
            except Exception:
                pass

            self._flush_capture(cap)

            if not handled:
                render_error("Unknown command")
        finally:
            if end_timer_on_exit:
                self._end_turn_timer()

    async def _submit_message(self, content: str | list) -> None:
        if _DEBUG:
            self._write_text("  [debug] worker started", style="dim yellow")
            self._write_text(
                f"  [debug] thread={self.session.thread_id!r} assistant={self.session.assistant_id!r}",
                style="dim yellow",
            )

        if not self.session.thread_id or not self.session.assistant_id:
            self._write_text(
                "  Not connected (missing thread_id or assistant_id). "
                "Try restarting with --tui.",
                style="bold red",
            )
            return

        from deepagent_tui.handlers.stream import extract_text_content

        display_text = (
            content if isinstance(content, str) else extract_text_content(content)
        )

        self.session.status = "streaming"
        self.session.messages.append({"role": "user", "content": content})

        state = StreamState()
        self._stream_buffer = ""
        self._start_response_slot()

        event_counts: dict[str, int] = {}
        try:
            stream = self.client.stream_message(
                self.session.thread_id, self.session.assistant_id, content
            )
            if _DEBUG:
                self._write_text("  [debug] stream object created, iterating…", style="dim yellow")
            await self._consume_stream(stream, state, event_counts)
            if _DEBUG or not event_counts:
                summary = ", ".join(f"{k}={v}" for k, v in event_counts.items()) or "0"
                style = "dim yellow" if event_counts else "bold red"
                self._write_text(f"  [debug] stream ended · events: {summary}", style=style)
            self._flush_usage(state)
            await self._handle_interrupts()

            try:
                await upsert_thread(
                    self.session.thread_id,
                    self.session.graph_id or "",
                    last_message=display_text[:100],
                    message_count=len(self.session.messages) + 1,
                )
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            # Swallow errors raised by the ESC-cancel path — the rollback flow
            # already restored UI state and we don't want a red banner for a
            # user-initiated cancel.
            if not self._cancelling:
                self._write_text(f"  Stream error: {e}", style="bold red")
                if _DEBUG:
                    self._write_text(traceback.format_exc(), style="red")
        finally:
            self._finalize_slot()
            self._stream_buffer = ""
            self.session.status = "idle"
            self._end_turn_timer()
            self._stream_worker = None
            self._active_run_id = None
            self._turn_start_index = None
            self._last_user_text = ""
            self._last_user_attachments = []

    async def _consume_stream(
        self,
        stream,
        state: StreamState,
        event_counts: dict[str, int] | None = None,
    ) -> None:
        from deepagent_tui.handlers.stream import extract_text_content

        async for chunk in stream:
            event_type = chunk.event
            data = chunk.data

            if event_counts is not None:
                event_counts[event_type] = event_counts.get(event_type, 0) + 1

            # With stream_subgraphs=True the SDK suffixes events emitted from
            # inside a subgraph as `"<event>|<namespace>"` (e.g.
            # `updates|tools:abc123`). The base event name still drives the
            # handler choice; the namespace tells us which subagent the event
            # belongs to. An empty namespace means the parent graph.
            base_event, _, ns = event_type.partition("|")

            # The SDK emits a single `metadata` chunk at run start carrying the
            # run_id. We need it so ESC can ask the server to roll the run back.
            if base_event == "metadata" and isinstance(data, dict):
                rid = data.get("run_id")
                if isinstance(rid, str):
                    self._active_run_id = rid

            if base_event == "messages/partial":
                # Only stream the parent agent's text into the response slot.
                # Subagent token streams would otherwise overwrite it mid-turn.
                if ns:
                    continue
                frag = process_messages_event(data, state)
                if frag:
                    if self._active_slot is None:
                        self._start_response_slot()
                    self._stream_buffer += frag
                    self._apply_streaming_text(self._stream_buffer)

            elif base_event == "updates" and isinstance(data, dict):
                if ns:
                    # Subagent-internal update: surface inner tool calls as
                    # progress lines on the parent task widget, ignore tool
                    # results and any other inner messages.
                    self._handle_subagent_update(ns, data)
                    continue

                accumulated = self._stream_buffer
                # Lock in whatever the streaming slot showed (if any).
                self._finalize_slot()
                self._stream_buffer = ""

                messages = process_updates_event(data, state)
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    msg_type = msg.get("type")
                    if msg_type == "ai":
                        ai_text = extract_text_content(msg.get("content", ""))
                        if ai_text.strip() and ai_text.strip() != accumulated.strip():
                            self._write_renderable(render_markdown(ai_text))
                        for tc in msg.get("tool_calls", []):
                            self._write_tool_call(format_tool_call(tc))
                    elif msg_type == "tool":
                        self._write_tool_result(format_tool_result(msg))

                # Show Thinking… in a fresh slot in case more streaming follows.
                self._start_response_slot()

        # Stream ended — drop the trailing thinking slot if nothing arrived.
        self._finalize_slot()
        self._stream_buffer = ""

    async def _handle_interrupts(self) -> None:
        while True:
            try:
                thread_state = await self.client.get_thread_state(self.session.thread_id)
            except Exception:
                return

            interrupts = extract_interrupts(thread_state)
            if not interrupts:
                return

            interrupt = interrupts[0]
            self.session.status = "interrupted"

            # No separate preview: the pending tool widget already shows the
            # diff/args for the in-flight call. Just attach the inline
            # approval below it.
            choice = await self._inline_approve(interrupt)
            if choice is None:
                choice = "reject"

            resume_value = build_resume_value(interrupt, choice, None)

            self.session.status = "streaming"
            state = StreamState()
            self._stream_buffer = ""
            self._start_response_slot()

            resume_stream = self.client.resume(
                self.session.thread_id, self.session.assistant_id, resume_value
            )
            await self._consume_stream(resume_stream, state)
            self._flush_usage(state)
            self._finalize_slot()

            # NB: don't return early on reject. The agent often reacts to a
            # rejection by trying a different approach (another tool call),
            # which surfaces as a fresh interrupt during the resume stream —
            # bailing here would leave that next call paused on the server
            # with no UI to approve it, ending the turn prematurely. Let the
            # loop keep polling until thread state has no pending interrupts.

    def _flush_usage(self, state: StreamState) -> None:
        if state.total_input_tokens or state.total_output_tokens:
            self.session.add_usage(state.total_input_tokens, state.total_output_tokens)
        if state.model and not self.session.model:
            self.session.model = state.model
        if (
            not self.session.workspace_root
            or not self.session.discovered_skills_from_state
        ):
            self.run_worker(self._discover_from_thread_state(), exclusive=False)

    async def _discover_from_thread_state(self) -> None:
        """Fetch skills_metadata from thread state. Register skills as dynamic
        slash commands and derive the workspace root from any skill path."""
        if not self.session.thread_id:
            return

        try:
            skills = await self.client.get_skills_from_state(self.session.thread_id)
        except Exception:
            skills = []

        if skills and not self.session.discovered_skills_from_state:
            from deepagent_tui.bootstrap import register_skill_command

            self.session.discovered_skills_from_state = True
            for sk in skills:
                name = sk.get("name", "") if isinstance(sk, dict) else ""
                if not name:
                    continue
                desc = sk.get("description", "")
                path = sk.get("path", "")
                self.session.discovered_tools[name] = desc
                register_skill_command(name, desc, path)

        if self.session.workspace_root:
            return

        for sk in skills:
            path = sk.get("path") if isinstance(sk, dict) else None
            if not path:
                continue
            try:
                root = str(Path(path).parents[3])
            except IndexError:
                continue
            self._apply_workspace_root(root)
            return

        try:
            state = await self.client.get_thread_state(self.session.thread_id)
        except Exception:
            return
        values = state.get("values", {}) if isinstance(state, dict) else {}
        for key in (
            "working_directory", "workspace", "project_root",
            "root_dir", "cwd", "workspace_dir",
        ):
            v = values.get(key) if isinstance(values, dict) else None
            if isinstance(v, str) and v.startswith("/"):
                self._apply_workspace_root(v)
                return

    def _apply_workspace_root(self, path: str) -> None:
        self.session.workspace_root = path
        try:
            self.query_one("#welcome", WelcomeBanner).refresh_content()
        except Exception:
            pass

    def on_chat_text_area_attachments_pasted(
        self, message: ChatTextArea.AttachmentsPasted
    ) -> None:
        new = [p for p in message.paths if p not in self._pending_attachments]
        if not new:
            return
        self._pending_attachments.extend(new)
        self._refresh_attachments_preview()

    def _refresh_attachments_preview(self) -> None:
        widget = self.query_one("#attachments", Static)
        paths = self._pending_attachments
        if not paths:
            widget.add_class("-hidden")
            widget.update("")
            return
        accent = _theme.ACCENT_COLOR
        lines = [
            Text(f"+ {Path(p).name}", style=f"dim {accent}") for p in paths
        ]
        hint = Text("  esc to clear", style="dim")
        widget.update(Group(*lines, hint))
        widget.remove_class("-hidden")
        self._scroll_to_input()

    async def _tui_pick(
        self,
        items: list[PickerItem],
        heading: str = "Select",
        hint: str | None = None,
        max_visible: int | None = None,
        subtitle: str | None = None,
        search_placeholder: str | None = None,
    ) -> Any:
        """Inline list picker for /resume, /fork, and similar commands.
        Called from a worker (commands run as workers in the TUI), so it
        can use push_screen_wait directly to suspend the worker until the
        user picks or cancels."""
        kwargs: dict[str, Any] = {
            "hint": hint,
            "max_visible": max_visible,
            "subtitle": subtitle,
        }
        if search_placeholder is not None:
            kwargs["search_placeholder"] = search_placeholder
        return await self.push_screen_wait(PickerScreen(items, heading, **kwargs))

    async def _tui_show_help(self) -> None:
        """Push the full-screen help view. Called from the /help command worker."""
        from deepagent_tui.ui.renderer import render_info

        await self.push_screen_wait(HelpScreen())
        render_info("Help dialog dismissed.")

    async def _tui_show_commands(self) -> None:
        """Push the full-screen commands view. Called from the /commands command worker."""
        from deepagent_tui.commands import builtin_commands
        from deepagent_tui.ui.renderer import render_info

        await self.push_screen_wait(CommandsScreen(builtin_commands()))
        render_info("Commands dialog dismissed.")

    async def _tui_show_status(self) -> None:
        """Push the full-screen status view. Called from the /status command worker."""
        from deepagent_tui.ui.renderer import render_info
        from deepagent_tui.utils.cost import format_cost, format_tokens

        s = self.session
        connection = [
            ("Server", settings.langgraph_url),
            ("Graph", s.graph_id or "not connected"),
            ("Assistant", s.assistant_id or "not connected"),
            ("Thread", s.thread_id or "none"),
            ("Model", s.model or "unknown"),
            ("Status", s.status),
        ]
        usage = [
            ("Tokens", f"{format_tokens(s.input_tokens)} in / {format_tokens(s.output_tokens)} out"),
            ("Cost", format_cost(s.total_cost)),
        ]
        await self.push_screen_wait(StatusScreen(connection, usage))
        render_info("Status dialog dismissed.")

    def _tui_set_input(self, text: str) -> None:
        """Fill the chat input bar with `text` and focus it. Used by pickers
        (e.g. /skills) that hand the user a prepared command to edit and send."""
        prompt = self._set_prompt_text(text)
        prompt.focus()

    def action_clear_log(self) -> None:
        container = self.query_one("#messages", Container)
        for child in list(container.children):
            child.remove()
        self._tool_widgets.clear()

    def action_scroll_history_up(self) -> None:
        try:
            self.query_one("#main", VerticalScroll).scroll_page_up(animate=False)
        except Exception:
            pass

    def action_scroll_history_down(self) -> None:
        try:
            self.query_one("#main", VerticalScroll).scroll_page_down(animate=False)
        except Exception:
            pass

    async def _replay_thread(
        self, messages: list[dict], *, header: str | None = None
    ) -> None:
        """Render past messages as static history. When `header` is given, the
        last mounted widget (the `❯ /command` submission for this turn) is
        preserved and a `⎿ {header}` line is mounted above the replayed
        conversation; otherwise the log is fully cleared before replay."""
        from deepagent_tui.handlers.stream import extract_text_content
        from deepagent_tui.ui.renderer import render_info

        if header is not None:
            children = list(self._messages.children)
            for child in children[:-1]:
                child.remove()
            self._tool_widgets.clear()
            render_info(header)
        else:
            self.action_clear_log()

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type") or msg.get("role", "")
            content = msg.get("content", "")

            if msg_type in ("user", "human"):
                text = extract_text_content(content)
                if text.strip():
                    widget = _user_message_widget(
                        _user_message_text(text), multiline="\n" in text
                    )
                    self._messages.mount(widget)
            elif msg_type == "ai":
                text = extract_text_content(content)
                if text.strip():
                    self._write_renderable(render_markdown(text))
                for tc in msg.get("tool_calls", []) or []:
                    self._write_tool_call(format_tool_call(tc))
            elif msg_type == "tool":
                self._write_tool_result(format_tool_result(msg))

        self._scroll_to_input()

    # ── Message rendering helpers ───────────────────────────────────────────

    @property
    def _messages(self) -> Container:
        return self.query_one("#messages", Container)

    def _scroll_to_input(self) -> None:
        """Scroll the message area so the most recent content sits flush
        against the chat bar. Defer to the next refresh so newly-mounted or
        just-updated widgets have laid out before we measure."""
        try:
            scroll = self.query_one("#main", VerticalScroll)
        except Exception:
            return
        scroll.scroll_end(animate=False)
        self.call_after_refresh(scroll.scroll_end, animate=False)

    def _write_text(self, text: str, style: str = "") -> None:
        self._write_renderable(Text(text, style=style) if style else Text(text))

    def _write_renderable(self, renderable: RenderableType) -> None:
        widget = Static(renderable, classes="msg")
        self._messages.mount(widget)
        self._scroll_to_input()

    def _write_cmd_renderable(self, renderable: RenderableType) -> None:
        """Sink for slash-command output. Mounts under `.msg-cmd` so the body
        sits flush under the `❯ /command` user submission without the
        one-row gap that `.msg` widgets get from their top margin."""
        widget = Static(renderable, classes="msg-cmd")
        self._messages.mount(widget)
        self._scroll_to_input()

    async def _inline_approve(self, interrupt: InterruptInfo) -> str | None:
        """Mount an InlineApproval at the bottom of the transcript, hand it
        focus, and await the user's choice. The chat bar/rules are hidden by
        toggling `.-approval-hidden` on each widget so the hint line is the
        last visible row, then restored afterwards."""
        import asyncio

        fut: asyncio.Future[str | None] = asyncio.get_event_loop().create_future()
        widget = InlineApproval(interrupt, fut, classes="msg")
        self._messages.mount(widget)
        self._set_approval_active(True)
        # Hiding the chat textarea drops focus; re-aim it at the approval
        # after the next refresh so digits/arrows reliably reach it.
        self.call_after_refresh(widget.focus)
        self._scroll_to_input()
        try:
            choice = await fut
        finally:
            self._set_approval_active(False)
            # Remove the approval widget entirely — once the user has chosen,
            # the pending tool widget (with its diff) is the only thing that
            # should remain, and it will flip to its success state when the
            # tool result arrives.
            try:
                await widget.remove()
            except Exception:
                pass
            try:
                self.query_one("#prompt", ChatTextArea).focus()
            except Exception:
                pass
            self._scroll_to_input()
        return choice

    def _begin_turn_timer(self) -> None:
        try:
            self.query_one("#hint-bar", HintBar).begin_timer()
        except Exception:
            pass

    def _end_turn_timer(self) -> None:
        try:
            self.query_one("#hint-bar", HintBar).end_timer()
        except Exception:
            pass

    def _reset_turn_timer(self) -> None:
        try:
            self.query_one("#hint-bar", HintBar).reset_timer()
        except Exception:
            pass

    def _set_approval_active(self, active: bool) -> None:
        """Show/hide the chat bar + adjacent rows while an inline approval
        is waiting. Each widget gets `.-approval-hidden`, which the CSS maps
        to `display: none`."""
        for sel in ("#chat-bar", "#chat-rule-top", "#chat-rule-bottom",
                    "#autocomplete", "#attachments", "#hint-bar"):
            try:
                w = self.query_one(sel)
            except Exception:
                continue
            if active:
                w.add_class("-approval-hidden")
            else:
                w.remove_class("-approval-hidden")
        # Keep a marker on the screen so the priority Esc/Tab bindings can
        # forward to the approval widget instead of running their normal
        # actions (priority bindings fire before widget on_key).
        if active:
            self.screen.add_class("-approval-active")
        else:
            self.screen.remove_class("-approval-active")

    def _stop_thinking_timer(self) -> None:
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
            self._thinking_timer = None

    def _start_response_slot(self) -> None:
        """Mount a new response widget at the end of #messages and begin the
        Thinking… animation in it. The same widget is later swapped to the
        streaming markdown so the layout doesn't bounce."""
        self._stop_thinking_timer()
        slot = Static(_thinking_renderable(0), classes="msg")
        self._messages.mount(slot)
        self._active_slot = slot
        self._thinking_frame = 0
        self._thinking_timer = self.set_interval(0.1, self._animate_thinking)
        self._scroll_to_input()

    def _animate_thinking(self) -> None:
        if self._active_slot is None or self._stream_buffer:
            return
        self._thinking_frame += 1
        self._active_slot.update(_thinking_renderable(self._thinking_frame))

    def _apply_streaming_text(self, text: str) -> None:
        """Replace the active slot's content with rendered markdown."""
        self._stop_thinking_timer()
        if self._active_slot is None:
            return
        self._active_slot.update(render_markdown(text))
        self._scroll_to_input()

    def _finalize_slot(self) -> None:
        """Stop the spinner. If the slot only ever showed Thinking… (no text
        arrived), remove it so it doesn't leave an empty line behind."""
        self._stop_thinking_timer()
        if self._active_slot is not None and not self._stream_buffer.strip():
            self._active_slot.remove()
        self._active_slot = None
        self._scroll_to_input()

    def _write_tool_call(self, tc: FormattedToolCall) -> None:
        from deepagent_tui.ui.tool_widgets import render_tool_call_widget

        # Resume streams (after HITL approval) re-emit the AI message
        # including its tool_calls, so the same tc.id can arrive twice. If we
        # already have a widget for this id, refresh it in place instead of
        # mounting a duplicate — otherwise the first widget gets orphaned
        # (un-tracked) and lingers above the eventual result widget.
        if tc.id and tc.id in self._tool_widgets:
            existing, _ = self._tool_widgets[tc.id]
            existing.update(render_tool_call_widget(tc, state="pending"))
            self._tool_widgets[tc.id] = (existing, tc)
            self._scroll_to_input()
            return

        widget = Static(render_tool_call_widget(tc, state="pending"), classes="msg")
        self._messages.mount(widget)
        if tc.id:
            self._tool_widgets[tc.id] = (widget, tc)
            if tc.is_subagent:
                self._subagent_progress[tc.id] = []
                self._pending_subagent_ids.append(tc.id)
        self._scroll_to_input()

    def _write_tool_result(self, result: FormattedToolResult) -> None:
        from deepagent_tui.ui.tool_widgets import (
            is_rejected_result,
            render_tool_call_widget,
            render_tool_result_widget,
        )

        entry = self._tool_widgets.pop(result.tool_call_id, None)
        call = entry[1] if entry else None
        result_render = render_tool_result_widget(result, call=call)
        if entry is not None:
            widget, tc = entry
            if is_rejected_result(result):
                state = "rejected"
            else:
                state = "error" if result.is_error else "success"
            progress = self._subagent_progress.pop(tc.id, None) if tc.is_subagent else None
            if tc.is_subagent:
                # Drop the namespace binding for this task. If the subagent
                # never streamed anything (no inner namespace seen), also pull
                # this id off the pending FIFO so a later subagent doesn't
                # inherit it.
                for ns, tid in list(self._subagent_ns_to_id.items()):
                    if tid == tc.id:
                        self._subagent_ns_to_id.pop(ns, None)
                if tc.id in self._pending_subagent_ids:
                    self._pending_subagent_ids.remove(tc.id)
            call_render = render_tool_call_widget(tc, state=state, progress=progress)
            # Re-use the call's widget so call + result share the same `.msg`
            # block. Mounting a second widget would insert a margin row, which
            # looks like a stray blank line between the header and its body.
            if result_render is None:
                widget.update(call_render)
            else:
                widget.update(Group(call_render, result_render))
            self._scroll_to_input()
        elif result_render is not None:
            self._write_renderable(result_render)

    def _handle_subagent_update(self, namespace: str, data: dict) -> None:
        """Stream a single `updates|<ns>` chunk from inside a subagent.
        Extracts inner tool calls and appends them as `⎿` lines to the
        owning Subagent widget."""
        from deepagent_tui.ui.tool_widgets import (
            _progress_summary,
            render_tool_call_widget,
        )

        task_id = self._subagent_ns_to_id.get(namespace)
        if task_id is None:
            # First event for this namespace — bind to the oldest unbound
            # subagent call. If we have none (unlikely; means a subagent
            # streamed before its parent call surfaced), drop the chunk.
            if not self._pending_subagent_ids:
                return
            task_id = self._pending_subagent_ids.pop(0)
            self._subagent_ns_to_id[namespace] = task_id

        entry = self._tool_widgets.get(task_id)
        if entry is None:
            return
        widget, tc = entry

        # Only inner tool calls become progress lines. Tool results and inner
        # model text are not surfaced — the goal is a minimal trace of what
        # the subagent is doing, not a full re-render of its turn.
        added = False
        for _node_name, node_output in data.items():
            if not isinstance(node_output, dict):
                continue
            for msg in node_output.get("messages", []) or []:
                if not isinstance(msg, dict) or msg.get("type") != "ai":
                    continue
                for raw_tc in msg.get("tool_calls", []) or []:
                    inner = format_tool_call(raw_tc)
                    self._subagent_progress.setdefault(task_id, []).append(
                        _progress_summary(inner)
                    )
                    added = True

        if not added:
            return
        progress = self._subagent_progress.get(task_id, [])
        widget.update(render_tool_call_widget(tc, state="pending", progress=progress))
        self._scroll_to_input()

    def _flush_capture(self, cap: "_Capture") -> None:
        raw = cap.buf.getvalue()
        if not raw:
            return
        for line in raw.splitlines():
            if line:
                rendered = Text.from_ansi(line)
                # Skip lines that decode to nothing visible — e.g. the
                # ANSI clear/home codes emitted by `console.clear()` in
                # /new. Mounting them would add a phantom `.msg` widget
                # whose `margin-top: 1` shows up as an extra blank row.
                if not rendered.plain.strip():
                    continue
                self._write_renderable(rendered)
            else:
                self._write_text("")


def _collapse_home(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~/" + path[len(home) + 1 :]
    return path


def _workspace_label(session: Session) -> str | None:
    if session.workspace_root:
        return _collapse_home(session.workspace_root)
    return None


def _gradient_line(line: str, width: int) -> Text:
    out = Text()
    span = max(1, width - 1)
    theme = _theme.current_theme()
    sr, sg, sb = theme.gradient_start
    er, eg, eb = theme.gradient_end
    for i, ch in enumerate(line):
        if ch == " ":
            out.append(" ")
            continue
        t = i / span
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        out.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return out


# ── Console capture helpers ────────────────────────────────────────────────


class _Capture:
    """Captures rich console output by swapping the singleton's `.file`."""

    def __init__(self) -> None:
        self.buf = io.StringIO()
        self._console: Console | None = None
        self._orig_file = None
        self._orig_force_terminal = None

    def __enter__(self) -> "_Capture":
        from deepagent_tui.ui import renderer as _r

        self._console = _r.console
        self._orig_file = self._console.file
        self._orig_force_terminal = self._console._force_terminal
        self._console.file = self.buf
        self._console._force_terminal = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._console is not None:
            self._console.file = self._orig_file
            self._console._force_terminal = self._orig_force_terminal


def _capture_console() -> _Capture:
    return _Capture()


def run_tui() -> None:
    """Synchronous entry point for the Textual TUI."""
    DeepAgentTUI().run()
