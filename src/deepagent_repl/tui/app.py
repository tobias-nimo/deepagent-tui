from __future__ import annotations

import io
import os
import traceback
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Input, RichLog, Static

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
    """Pinned top banner: ASCII graph name, workspace · thread, /help."""

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

        accent = _accent_hex()
        ws = _workspace_label(self._session)
        tid_short = (self._session.thread_id or "")[:12]

        rows.append(Text(""))
        bits: list[tuple[str, str]] = []
        if ws:
            bits.append((ws, ""))
            bits.append(("  ·  ", "dim"))
        bits.append(("thread ", "dim"))
        bits.append((tid_short, "dim"))
        rows.append(Text.assemble(*bits))

        rows.append(
            Text.assemble(("/help", f"bold {accent}"), (" for commands.", "dim"))
        )

        self.update(Group(*rows))


class DeepAgentTUI(App):
    """Textual front-end for the Deep Agent REPL."""

    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }

    #log {
        height: 1fr;
        padding: 1 2;
        background: $background;
        border: none;
        scrollbar-size: 1 1;
    }

    #streaming {
        height: auto;
        padding: 0 2;
        background: $background;
        color: $text;
    }
    #streaming.-hidden { display: none; }

    #input-wrap {
        dock: bottom;
        height: auto;
        padding: 0 1 0 1;
        background: $background;
    }

    #prompt {
        border: round ACCENT;
        background: $background;
        color: $text;
        padding: 0 1;
    }
    #prompt:focus {
        border: round ACCENT;
        background: $background;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $background;
        color: $text-muted;
    }

    WelcomeBanner {
        height: auto;
        padding: 1 2 0 2;
        background: $background;
    }
    """.replace("ACCENT", _accent_hex())

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client = AgentClient(
            url=settings.langgraph_url, api_key=settings.langsmith_api_key
        )
        self.session = Session()
        self._stream_buffer: str = ""

    def compose(self) -> ComposeResult:
        yield WelcomeBanner(self.session, id="welcome")
        yield RichLog(
            id="log", auto_scroll=True, wrap=True, markup=False, highlight=False
        )
        yield Static("", id="streaming", classes="-hidden")
        with Container(id="input-wrap"):
            yield Input(id="prompt", placeholder="Type your message…  (/help · ctrl+l · ctrl+c)")
        yield StatusBar(self.session, id="status-bar")

    async def on_mount(self) -> None:
        log = self._log_widget
        welcome = self.query_one("#welcome", WelcomeBanner)
        welcome.set_connecting(settings.langgraph_url)

        from deepagent_repl.cli import connect, discover_and_register_skills

        with _capture_console() as cap:
            try:
                ok = await connect(self.client, self.session)
            except Exception as e:  # noqa: BLE001
                ok = False
                log.write(Text(f"  Connection error: {e}", style="bold red"))
                if _DEBUG:
                    log.write(Text(traceback.format_exc(), style="red"))
        _flush_capture_to_log(log, cap)

        if not ok:
            log.write(Text("  Failed to connect — exiting in 3s.", style="bold red"))
            self.set_timer(3.0, self.exit)
            return

        with _capture_console() as cap:
            try:
                await discover_and_register_skills(self.client, self.session)
            except Exception as e:  # noqa: BLE001
                log.write(Text(f"  Skill discovery skipped: {e}", style="dim red"))
        _flush_capture_to_log(log, cap)

        welcome.set_connecting(None)
        self.query_one("#prompt", Input).focus()

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        text = message.value.strip()
        if not text:
            return
        message.input.value = ""

        log = self._log_widget
        log.write(Text(""))
        log.write(Text(f"❯ {text}", style="bold"))
        log.write(Text(""))

        from deepagent_repl.commands import is_command

        if is_command(text):
            await self._run_command(text)
            return

        if _DEBUG:
            log.write(Text("  [debug] scheduling stream worker", style="dim yellow"))

        worker = self.run_worker(
            self._submit_message(text),
            exclusive=True,
            name="stream",
            exit_on_error=False,
        )
        self._track_worker(worker)

    def _track_worker(self, worker) -> None:
        """Surface worker failures into the log so they aren't silently swallowed."""
        log = self._log_widget

        async def _watch() -> None:
            await worker.wait()
            err = getattr(worker, "error", None)
            if err is not None:
                log.write(Text(f"  Worker failed: {err!r}", style="bold red"))
                if _DEBUG:
                    import traceback as _tb
                    tb_str = "".join(_tb.format_exception(type(err), err, err.__traceback__))
                    log.write(Text(tb_str, style="red"))

        self.run_worker(_watch(), exclusive=False, name="worker-watch")

    async def _run_command(self, text: str) -> None:
        from deepagent_repl.commands import dispatch as dispatch_command
        from deepagent_repl.commands import dynamic_commands

        log = self._log_widget

        with _capture_console() as cap:
            try:
                handled = await dispatch_command(self.client, self.session, text)
            except Exception as e:  # noqa: BLE001
                handled = True
                log.write(Text(f"  Command error: {e}", style="red"))
                if _DEBUG:
                    log.write(Text(traceback.format_exc(), style="red"))

        _flush_capture_to_log(log, cap)

        if not handled:
            parts = text[1:].split(None, 1)
            name = parts[0] if parts else text[1:]
            args = parts[1] if len(parts) > 1 else ""
            if name in dynamic_commands():
                prompt = f"Use the {name} skill"
                if args:
                    prompt += f": {args}"
                log.write(Text(f"  Invoking skill: {name}", style="dim"))
                worker = self.run_worker(
                    self._submit_message(prompt),
                    exclusive=True,
                    name="stream",
                    exit_on_error=False,
                )
                self._track_worker(worker)
            else:
                log.write(Text(f"  Unknown command: /{name}", style="red"))

    async def _submit_message(self, text: str) -> None:
        log = self._log_widget
        try:
            streaming = self.query_one("#streaming", Static)
        except Exception as e:  # noqa: BLE001
            log.write(Text(f"  Worker setup failed: {e}", style="bold red"))
            return

        if _DEBUG:
            log.write(Text("  [debug] worker started", style="dim yellow"))
            log.write(
                Text(
                    f"  [debug] thread={self.session.thread_id!r} assistant={self.session.assistant_id!r}",
                    style="dim yellow",
                )
            )

        if not self.session.thread_id or not self.session.assistant_id:
            log.write(
                Text(
                    "  Not connected (missing thread_id or assistant_id). "
                    "Try restarting with --tui.",
                    style="bold red",
                )
            )
            return

        self.session.status = "streaming"
        self.session.messages.append({"role": "user", "content": text})

        state = StreamState()
        self._stream_buffer = ""
        streaming.update("")
        streaming.remove_class("-hidden")

        event_counts: dict[str, int] = {}
        try:
            stream = self.client.stream_message(
                self.session.thread_id, self.session.assistant_id, text
            )
            if _DEBUG:
                log.write(Text("  [debug] stream object created, iterating…", style="dim yellow"))
            await self._consume_stream(stream, state, log, streaming, event_counts)
            if _DEBUG or not event_counts:
                summary = ", ".join(f"{k}={v}" for k, v in event_counts.items()) or "0"
                style = "dim yellow" if event_counts else "bold red"
                log.write(Text(f"  [debug] stream ended · events: {summary}", style=style))
            self._flush_usage(state)
            await self._handle_interrupts(log, streaming)

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
            log.write(Text(f"  Stream error: {e}", style="bold red"))
            if _DEBUG:
                log.write(Text(traceback.format_exc(), style="red"))
        finally:
            streaming.add_class("-hidden")
            streaming.update("")
            self._stream_buffer = ""
            self.session.status = "idle"

    async def _consume_stream(
        self,
        stream,
        state: StreamState,
        log: RichLog,
        streaming: Static,
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
                    self._stream_buffer += frag
                    streaming.update(render_markdown(self._stream_buffer))

            elif event_type == "updates" and isinstance(data, dict):
                # Snapshot what we've streamed so far before resetting.
                accumulated = self._stream_buffer
                if accumulated.strip():
                    log.write(render_markdown(accumulated))
                    log.write(Text(""))
                self._stream_buffer = ""
                streaming.update("")

                messages = process_updates_event(data, state)
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    msg_type = msg.get("type")
                    if msg_type == "ai":
                        ai_text = extract_text_content(msg.get("content", ""))
                        if ai_text.strip() and ai_text.strip() != accumulated.strip():
                            log.write(render_markdown(ai_text))
                            log.write(Text(""))
                        for tc in msg.get("tool_calls", []):
                            _write_tool_call(log, format_tool_call(tc))
                    elif msg_type == "tool":
                        _write_tool_result(log, format_tool_result(msg))

        if self._stream_buffer.strip():
            log.write(render_markdown(self._stream_buffer))
            log.write(Text(""))
            self._stream_buffer = ""

    async def _handle_interrupts(self, log: RichLog, streaming: Static) -> None:
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

            log.write(_build_interrupt_panel(interrupt))

            from deepagent_repl.storage.rules import match_rule

            tool_name = _interrupt_tool_name(interrupt)
            auto_action = match_rule(tool_name) if tool_name else None
            if auto_action == "allow":
                choice = "approve"
                log.write(Text(f"  Auto-{choice} by rule.", style="dim"))
            elif auto_action == "deny":
                choice = "reject"
                log.write(Text(f"  Auto-{choice} by rule.", style="dim"))
            else:
                choice = await self.push_screen_wait(ApprovalScreen(interrupt))
                if choice is None:
                    choice = "reject"

            log.write(Text(f"  → {choice}", style="dim"))

            resume_value = build_resume_value(interrupt, choice, None)

            self.session.status = "streaming"
            state = StreamState()
            self._stream_buffer = ""
            streaming.update("")
            streaming.remove_class("-hidden")

            resume_stream = self.client.resume(
                self.session.thread_id, self.session.assistant_id, resume_value
            )
            await self._consume_stream(resume_stream, state, log, streaming)
            self._flush_usage(state)
            streaming.add_class("-hidden")

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
        """After a stream, ask the server what workspace the agent is using.

        Tries, in order:
          1. skills_metadata paths — split on '/.claude/skills/' to get the root
          2. common path-like keys in thread state values (working_directory,
             workspace, project_root, root_dir, cwd, workspace_dir)
        """
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
        self._log_widget.clear()

    @property
    def _log_widget(self) -> RichLog:
        return self.query_one("#log", RichLog)


# Cyan → magenta gradient (Qwen-style). Falls back to grey/black-on-default
# automatically: terminals without truecolor downgrade hex styles to the
# nearest 256-color, and Rich's `dim` attribute degrades the result toward
# greyscale on monochrome terminals.
_GRADIENT_START = (34, 211, 238)   # cyan-400  #22d3ee
_GRADIENT_END = (217, 70, 239)     # fuchsia-500 #d946ef


def _collapse_home(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~/" + path[len(home) + 1 :]
    return path


def _workspace_label(session: Session) -> str | None:
    """Server-side workspace if known. None if the agent hasn't told us yet
    (no client cwd fallback — wrong info is worse than no info)."""
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


def _write_tool_call(log: RichLog, tc: FormattedToolCall) -> None:
    if tc.is_subagent:
        title = f"subagent: {tc.subagent_name or tc.name}"
        body = tc.subagent_input or ""
        style = "magenta"
    else:
        title = tc.name
        body = _format_args(tc.args)
        style = _theme.ACCENT_COLOR
    if body:
        log.write(
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
        log.write(Text(f"  {title}", style=f"bold {style}"))


def _write_tool_result(log: RichLog, result: FormattedToolResult) -> None:
    style = "red" if result.is_error else "green"
    icon = "x" if result.is_error else "ok"
    header = Text(f"  [{icon}] {result.name}", style=f"bold {style}")
    if result.summary:
        log.write(
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
        log.write(header)


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


def _flush_capture_to_log(log: RichLog, cap: _Capture) -> None:
    raw = cap.buf.getvalue()
    if not raw:
        return
    for line in raw.splitlines():
        if line:
            log.write(Text.from_ansi(line))
        else:
            log.write(Text(""))


def run_tui() -> None:
    """Synchronous entry point for the Textual TUI."""
    DeepAgentTUI().run()
