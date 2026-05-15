from __future__ import annotations

import io
import os
import traceback
from typing import Any

from rich.console import Console, Group
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Input, Rule, Static
from textual.widgets import OptionList
from textual.widgets.option_list import Option

import deepagent_repl.ui.theme as _theme
from deepagent_repl.client import AgentClient
from deepagent_repl.config import settings
from deepagent_repl.handlers.interrupt import (
    InterruptInfo,
    build_resume_value,
    extract_interrupts,
)
from deepagent_repl.handlers.stream import (
    StreamState,
    process_messages_event,
    process_updates_event,
)
from deepagent_repl.handlers.tools import (
    FormattedToolCall,
    FormattedToolResult,
    format_tool_call,
    format_tool_result,
)
from deepagent_repl.session import Session
from deepagent_repl.storage.db import upsert_thread
from deepagent_repl.tui.screens import ApprovalScreen
from deepagent_repl.ui.markdown import render_markdown

_DEBUG = os.environ.get("DEEPAGENT_DEBUG") == "1"

# Muted, serious blue used for slash/question hints and autocomplete entries —
# distinct from the (often vivid) user accent colour.
_COMMAND_BLUE = "#5b7ca8"


def _accent_hex() -> str:
    """Return the user's accent colour as a hex string usable by Textual CSS."""
    color = _theme.ACCENT_COLOR
    if color.startswith("#"):
        return color
    named = {
        "cyan": "#22d3ee",
        "blue": "#3b82f6",
        "green": "#22c55e",
        "magenta": "#d946ef",
        "red": "#ef4444",
        "yellow": "#eab308",
        "white": "#f5f5f5",
        "bright_cyan": "#67e8f9",
        "bright_blue": "#60a5fa",
        "bright_green": "#4ade80",
        "bright_magenta": "#f0abfc",
        "bright_red": "#fca5a5",
        "bright_yellow": "#fde047",
        "bright_white": "#ffffff",
    }
    return named.get(color, "#22d3ee")


class StatusBar(Static):
    """Single-line bottom status bar that updates from session state."""

    def __init__(self, session: Session, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._session = session

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        from deepagent_repl.utils.cost import format_cost, format_tokens

        s = self._session
        cwd = os.path.basename(os.getcwd()) or "/"
        graph = s.graph_id or "—"
        tid_short = (s.thread_id or "—")[:8]
        model = s.model or "—"
        toks = f"{format_tokens(s.input_tokens)}↑ {format_tokens(s.output_tokens)}↓"
        cost = format_cost(s.total_cost)
        status_tag = f" [{s.status}]" if s.status != "idle" else ""
        self.update(
            f" {cwd} │ {graph} │ {model} │ thread {tid_short} │ {toks} │ {cost}{status_tag}"
        )


class WelcomeBanner(Static):
    """Top banner: ASCII graph name, workspace · thread, /help. Scrolls with content."""

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

        ws = _workspace_label(self._session)

        rows.append(Text(""))
        if ws:
            rows.append(Text(ws, style="dim"))

        sep = Text("  ◆  ", style="dim")
        rows.append(Text(""))
        rows.append(
            Text.assemble(
                ("/", f"bold {_COMMAND_BLUE}"),
                (" for commands", "dim"),
                sep,
                ("?", f"bold {_COMMAND_BLUE}"),
                (" for shortcuts", "dim"),
            )
        )

        self.update(Group(*rows))


_THINKING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _thinking_renderable(frame: int) -> Text:
    spinner = _THINKING_FRAMES[frame % len(_THINKING_FRAMES)]
    accent = _theme.ACCENT_COLOR
    return Text.assemble((spinner, f"bold {accent}"), ("  Thinking…", "dim"))


class ChatBar(Container):
    """Bordered, multi-line chat input box with a leading ❯ symbol."""

    DEFAULT_CSS = ""  # styled via app CSS

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-bar-row"):
            yield Static("❯", id="chat-prompt-icon")
            yield Input(id="prompt", placeholder="Type your message…")


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
        padding: 0;
        margin: 1 0 1 0;
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

    ChatBar {
        height: 1;
        border: none;
        background: $background;
        padding: 0 2;
    }

    #chat-bar-row {
        height: 1;
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
        height: 1;
    }
    #prompt:focus {
        border: none;
        background: $background;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $background;
        color: $text-muted;
    }
    """.replace("ACCENT", _accent_hex())

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
        Binding("escape", "hide_autocomplete", "Hide autocomplete", show=False),
        Binding("tab", "complete_command", "Complete", show=False, priority=True),
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

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="main"):
            yield WelcomeBanner(self.session, id="welcome")
            yield Container(id="messages")
            yield Rule(line_style="solid", id="chat-rule-top")
            yield ChatBar(id="chat-bar")
            yield Rule(line_style="solid", id="chat-rule-bottom")
            yield OptionList(id="autocomplete", classes="-hidden")
        yield StatusBar(self.session, id="status-bar")

    async def on_mount(self) -> None:
        welcome = self.query_one("#welcome", WelcomeBanner)
        welcome.set_connecting(settings.langgraph_url)

        from deepagent_repl.cli import connect, discover_and_register_skills

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
        self.query_one("#prompt", Input).focus()

    # ── Input / autocomplete ────────────────────────────────────────────────

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        self._refresh_autocomplete(event.value)

    def _refresh_autocomplete(self, value: str) -> None:
        ac = self.query_one("#autocomplete", OptionList)
        if not value.startswith("/"):
            was_visible = "-hidden" not in ac.classes
            ac.add_class("-hidden")
            ac.clear_options()
            if was_visible:
                self._scroll_to_input()
            return

        from deepagent_repl.commands import all_commands

        prefix = value[1:].split(None, 1)[0] if len(value) > 1 else ""
        matches = sorted(
            (name, desc)
            for name, desc in all_commands().items()
            if name.startswith(prefix)
        )
        ac.clear_options()
        if not matches:
            was_visible = "-hidden" not in ac.classes
            ac.add_class("-hidden")
            if was_visible:
                self._scroll_to_input()
            return

        name_width = max(len(n) for n, _ in matches) + 2
        for name, desc in matches[:20]:
            padded = f"/{name}".ljust(name_width)
            label = Text.assemble(
                (padded, f"bold {_COMMAND_BLUE}"),
                ("  ", ""),
                (desc or "", "dim"),
            )
            ac.add_option(Option(label, id=name))
        ac.remove_class("-hidden")
        ac.refresh(layout=True)
        self._scroll_to_input()

    def action_hide_autocomplete(self) -> None:
        ac = self.query_one("#autocomplete", OptionList)
        ac.add_class("-hidden")
        ac.clear_options()
        self._scroll_to_input()

    def action_complete_command(self) -> None:
        ac = self.query_one("#autocomplete", OptionList)
        if "-hidden" in ac.classes:
            return
        if ac.option_count == 0:
            return
        first = ac.get_option_at_index(0)
        if first.id is None:
            return
        prompt = self.query_one("#prompt", Input)
        prompt.value = f"/{first.id} "
        prompt.cursor_position = len(prompt.value)
        self.action_hide_autocomplete()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        # Only the autocomplete OptionList lives in the main app.
        if event.option_list.id != "autocomplete":
            return
        if event.option_id is None:
            return
        prompt = self.query_one("#prompt", Input)
        prompt.value = f"/{event.option_id} "
        prompt.cursor_position = len(prompt.value)
        self.action_hide_autocomplete()
        prompt.focus()

    # ── Submit / commands ───────────────────────────────────────────────────

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        text = message.value.strip()
        if not text:
            return
        message.input.value = ""
        self.action_hide_autocomplete()

        widget = Static(Text(f"❯ {text}", style="bold"), classes="msg-user")
        self._messages.mount(widget)
        self._scroll_to_input()

        from deepagent_repl.commands import is_command

        if is_command(text):
            await self._run_command(text)
            return

        if _DEBUG:
            self._write_text("  [debug] scheduling stream worker", style="dim yellow")

        worker = self.run_worker(
            self._submit_message(text),
            exclusive=True,
            name="stream",
            exit_on_error=False,
        )
        self._track_worker(worker)

    def _track_worker(self, worker) -> None:
        async def _watch() -> None:
            await worker.wait()
            err = getattr(worker, "error", None)
            if err is not None:
                self._write_text(f"  Worker failed: {err!r}", style="bold red")
                if _DEBUG:
                    import traceback as _tb
                    tb_str = "".join(_tb.format_exception(type(err), err, err.__traceback__))
                    self._write_text(tb_str, style="red")

        self.run_worker(_watch(), exclusive=False, name="worker-watch")

    async def _run_command(self, text: str) -> None:
        from deepagent_repl.commands import dispatch as dispatch_command
        from deepagent_repl.commands import dynamic_commands

        parts = text[1:].split(None, 1)
        name = parts[0] if parts else ""

        # /clear in TUI: clear the message log directly. The registered command
        # writes ANSI clear codes to the rich console, which the TUI captures
        # and discards — so the underlying command is a no-op here.
        if name == "clear":
            self.action_clear_log()
            return

        with _capture_console() as cap:
            try:
                handled = await dispatch_command(self.client, self.session, text)
            except Exception as e:  # noqa: BLE001
                handled = True
                self._write_text(f"  Command error: {e}", style="red")
                if _DEBUG:
                    self._write_text(traceback.format_exc(), style="red")

        # /new clears the screen before creating a new thread; mirror that in
        # the TUI by wiping the message log after the command runs.
        if name == "new" and handled:
            self.action_clear_log()

        self._flush_capture(cap)

        if not handled:
            parts = text[1:].split(None, 1)
            name = parts[0] if parts else text[1:]
            args = parts[1] if len(parts) > 1 else ""
            if name in dynamic_commands():
                prompt = f"Use the {name} skill"
                if args:
                    prompt += f": {args}"
                self._write_text(f"  Invoking skill: {name}", style="dim")
                worker = self.run_worker(
                    self._submit_message(prompt),
                    exclusive=True,
                    name="stream",
                    exit_on_error=False,
                )
                self._track_worker(worker)
            else:
                self._write_text(f"  Unknown command: /{name}", style="red")

    async def _submit_message(self, text: str) -> None:
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

        self.session.status = "streaming"
        self.session.messages.append({"role": "user", "content": text})

        state = StreamState()
        self._stream_buffer = ""
        self._start_response_slot()

        event_counts: dict[str, int] = {}
        try:
            stream = self.client.stream_message(
                self.session.thread_id, self.session.assistant_id, text
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
                    last_message=text[:100],
                    message_count=len(self.session.messages) + 1,
                )
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            self._write_text(f"  Stream error: {e}", style="bold red")
            if _DEBUG:
                self._write_text(traceback.format_exc(), style="red")
        finally:
            self._finalize_slot()
            self._stream_buffer = ""
            self.session.status = "idle"

    async def _consume_stream(
        self,
        stream,
        state: StreamState,
        event_counts: dict[str, int] | None = None,
    ) -> None:
        from deepagent_repl.handlers.stream import extract_text_content

        async for chunk in stream:
            event_type = chunk.event
            data = chunk.data

            if event_counts is not None:
                event_counts[event_type] = event_counts.get(event_type, 0) + 1

            if event_type == "messages/partial":
                frag = process_messages_event(data, state)
                if frag:
                    if self._active_slot is None:
                        self._start_response_slot()
                    self._stream_buffer += frag
                    self._apply_streaming_text(self._stream_buffer)

            elif event_type == "updates" and isinstance(data, dict):
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

            self._write_renderable(_build_interrupt_panel(interrupt))

            from deepagent_repl.storage.rules import match_rule

            tool_name = _interrupt_tool_name(interrupt)
            auto_action = match_rule(tool_name) if tool_name else None
            if auto_action == "allow":
                choice = "approve"
                self._write_text(f"  Auto-{choice} by rule.", style="dim")
            elif auto_action == "deny":
                choice = "reject"
                self._write_text(f"  Auto-{choice} by rule.", style="dim")
            else:
                choice = await self.push_screen_wait(ApprovalScreen(interrupt))
                if choice is None:
                    choice = "reject"

            self._write_text(f"  → {choice}", style="dim")

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

            if choice.lower() in ("reject", "deny", "no"):
                return

    def _flush_usage(self, state: StreamState) -> None:
        if state.total_input_tokens or state.total_output_tokens:
            self.session.add_usage(state.total_input_tokens, state.total_output_tokens)
        if state.model and not self.session.model:
            self.session.model = state.model
        if not self.session.workspace_root:
            self.run_worker(self._derive_workspace_root(), exclusive=False)

    async def _derive_workspace_root(self) -> None:
        if not self.session.thread_id:
            return

        try:
            skills = await self.client.get_skills_from_state(self.session.thread_id)
        except Exception:
            skills = []

        for sk in skills:
            path = sk.get("path") if isinstance(sk, dict) else None
            if not path:
                continue
            marker = "/.claude/skills/"
            if marker in path:
                self.session.workspace_root = path.split(marker, 1)[0]
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
                self.session.workspace_root = v
                return

    def action_clear_log(self) -> None:
        container = self.query_one("#messages", Container)
        for child in list(container.children):
            child.remove()

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
        self._thinking_timer = self.set_interval(0.08, self._animate_thinking)
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
        if tc.is_subagent:
            title = f"subagent: {tc.subagent_name or tc.name}"
            body = tc.subagent_input or ""
            style = "magenta"
        else:
            title = tc.name
            body = _format_args(tc.args)
            style = _theme.ACCENT_COLOR
        if body:
            self._write_renderable(
                Panel(
                    Text(body, style="dim"),
                    title=Text(f" {title} ", style=f"bold {style}"),
                    title_align="left",
                    border_style=f"dim {style}",
                    padding=(0, 1),
                    expand=False,
                )
            )
        else:
            self._write_text(f"  {title}", style=f"bold {style}")

    def _write_tool_result(self, result: FormattedToolResult) -> None:
        style = "red" if result.is_error else "green"
        icon = "x" if result.is_error else "ok"
        header = Text(f"  [{icon}] {result.name}", style=f"bold {style}")
        if result.summary:
            self._write_renderable(
                Panel(
                    Text(result.summary, style="dim"),
                    title=header,
                    title_align="left",
                    border_style=f"dim {style}",
                    padding=(0, 1),
                    expand=False,
                )
            )
        else:
            self._write_renderable(header)

    def _flush_capture(self, cap: "_Capture") -> None:
        raw = cap.buf.getvalue()
        if not raw:
            return
        for line in raw.splitlines():
            if line:
                self._write_renderable(Text.from_ansi(line))
            else:
                self._write_text("")


# Cyan → magenta gradient (Qwen-style).
_GRADIENT_START = (34, 211, 238)
_GRADIENT_END = (217, 70, 239)


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
    sr, sg, sb = _GRADIENT_START
    er, eg, eb = _GRADIENT_END
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


def _interrupt_tool_name(interrupt: InterruptInfo) -> str | None:
    if isinstance(interrupt.value, dict):
        for ar in interrupt.value.get("action_requests", []):
            if isinstance(ar, dict) and ar.get("name"):
                return ar["name"]
        return (
            interrupt.value.get("tool_name")
            or interrupt.value.get("action")
            or interrupt.value.get("name")
            or interrupt.value.get("type")
        )
    return None


def _build_interrupt_panel(interrupt: InterruptInfo) -> Panel:
    items: list[Text] = [Text(interrupt.description or "Action required", style="bold")]
    args_dict: dict = {}
    if isinstance(interrupt.value, dict):
        for ar in interrupt.value.get("action_requests", []):
            if isinstance(ar.get("args"), dict):
                args_dict.update(ar["args"])
        if not args_dict and isinstance(interrupt.value.get("args"), dict):
            args_dict = interrupt.value["args"]
    for key, val in args_dict.items():
        val_str = str(val).replace("\n", " ")
        if len(val_str) > 60:
            val_str = val_str[:57] + "..."
        items.append(Text(f"+ {key}  {val_str}", style="dim"))
    return Panel(
        Group(*items),
        title=Text(" Interrupt ", style="bold yellow"),
        title_align="left",
        border_style="yellow",
        padding=(0, 1),
        expand=False,
    )


def _format_args(args: dict, max_total: int = 120) -> str:
    if not args:
        return ""
    parts: list[str] = []
    total = 0
    for key, val in args.items():
        val_str = str(val).replace("\n", " ").strip()
        if len(val_str) > 60:
            val_str = val_str[:57] + "..."
        part = f"{key}={val_str}"
        total += len(part)
        if total > max_total and parts:
            parts.append("...")
            break
        parts.append(part)
    return ", ".join(parts)


# ── Console capture helpers ────────────────────────────────────────────────


class _Capture:
    """Captures rich console output by swapping the singleton's `.file`."""

    def __init__(self) -> None:
        self.buf = io.StringIO()
        self._console: Console | None = None
        self._orig_file = None
        self._orig_force_terminal = None

    def __enter__(self) -> "_Capture":
        from deepagent_repl.ui import renderer as _r

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
