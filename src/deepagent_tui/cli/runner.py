"""Headless run engine for the CLI.

Mirrors the TUI's streaming path (`tui/app.py` `_submit_message` /
`_handle_interrupts`) without any widgets: connect, consume the stream into
plain-text output, then auto-approve tool interrupts (abort on a non-tool
question). Every data primitive is reused from the shared layers.
"""

from __future__ import annotations

import sys

from rich.console import Console

from deepagent_tui.bootstrap import connect
from deepagent_tui.cli.output import Output, print_thread_list
from deepagent_tui.client import AgentClient
from deepagent_tui.config import settings
from deepagent_tui.handlers.interrupt import (
    InterruptInfo,
    _is_hitl_middleware_interrupt,
    build_resume_value,
    extract_interrupts,
)
from deepagent_tui.handlers.stream import (
    StreamState,
    extract_text_content,
    process_messages_event,
    process_updates_event,
)
from deepagent_tui.handlers.tools import format_tool_call, format_tool_result
from deepagent_tui.session import Session
from deepagent_tui.storage.db import get_thread, list_threads, upsert_thread

_err_console = Console(stderr=True)


def _route_render_to_stderr() -> None:
    """Send bootstrap's `render_info`/`render_error` to stderr so stdout stays
    clean (pure JSON in `--json`, just the answer when piping)."""
    from deepagent_tui.ui.renderer import set_mount_sink

    set_mount_sink(lambda renderable: _err_console.print(renderable))


class _Engine:
    """Consumes streams into an `Output`, accumulating the assistant answer."""

    def __init__(self, out: Output) -> None:
        self.out = out
        self.answer = ""
        self._printed_tc_ids: set[str] = set()

    async def consume(self, stream, state: StreamState) -> None:
        # Text streamed via token chunks since the last `updates` boundary —
        # lets us avoid re-emitting the same text when it also arrives whole in
        # the updates event (mirrors the TUI's `accumulated` check).
        stream_buffer = ""

        async for chunk in stream:
            base_event, _, ns = chunk.event.partition("|")
            data = chunk.data

            if base_event == "messages/partial":
                if ns:  # subagent token stream — skip, keep parent answer clean
                    continue
                frag = process_messages_event(data, state)
                if frag:
                    stream_buffer += frag
                    self.answer += frag
                    self.out.stream_text(frag)

            elif base_event == "updates" and isinstance(data, dict):
                if ns:  # subagent-internal update — not surfaced in the CLI
                    continue
                accumulated = stream_buffer
                stream_buffer = ""
                for msg in process_updates_event(data, state):
                    if not isinstance(msg, dict):
                        continue
                    mtype = msg.get("type")
                    if mtype == "ai":
                        ai_text = extract_text_content(msg.get("content", ""))
                        if ai_text.strip() and ai_text.strip() != accumulated.strip():
                            self.answer += ai_text
                            self.out.stream_text(ai_text)
                        for tc in msg.get("tool_calls", []):
                            tcid = tc.get("id", "")
                            if tcid and tcid in self._printed_tc_ids:
                                continue
                            if tcid:
                                self._printed_tc_ids.add(tcid)
                            self.out.tool_call(format_tool_call(tc).summary)
                    elif mtype == "tool":
                        self.out.tool_result(format_tool_result(msg))

    async def handle_interrupts(
        self, client: AgentClient, session: Session
    ) -> InterruptInfo | None:
        """Auto-approve tool interrupts until the run is clean. Returns the
        interrupt that aborted the run (a non-tool question), or None."""
        while True:
            try:
                thread_state = await client.get_thread_state(session.thread_id)
            except Exception:
                return None

            interrupts = extract_interrupts(thread_state)
            if not interrupts:
                return None

            interrupt = interrupts[0]
            if not _is_hitl_middleware_interrupt(interrupt.value):
                return interrupt  # question / custom-options → caller aborts

            resume_value = build_resume_value(interrupt, "approve", None)
            await self.consume(
                client.resume(session.thread_id, session.assistant_id, resume_value),
                StreamState(),
            )


async def _connect(client: AgentClient | None = None) -> tuple[AgentClient, Session] | None:
    _route_render_to_stderr()
    if client is None:
        client = AgentClient(url=settings.langgraph_url, api_key=settings.langsmith_api_key)
    session = Session()
    ok = await connect(client, session)
    if not ok:
        return None
    return client, session


async def _upsert(client: AgentClient, session: Session, last_message: str) -> None:
    try:
        state = await client.get_thread_state(session.thread_id)
        count = len(state.get("values", {}).get("messages", []) or [])
    except Exception:
        count = len(session.messages)
    try:
        await upsert_thread(
            session.thread_id,
            session.graph_id or "",
            last_message=last_message[:100],
            message_count=count,
        )
    except Exception:
        pass


async def _resolve_thread_id(client: AgentClient, raw: str) -> str | None:
    """Resolve a full/partial id: local DB → prefix match → server lookup."""
    record = await get_thread(raw)
    if record:
        return record["id"]

    rows = await list_threads(limit=200)
    matches = [t for t in rows if t["id"].startswith(raw)]
    if len(matches) == 1:
        return matches[0]["id"]
    if len(matches) > 1:
        print(
            f"Ambiguous thread id prefix '{raw}' — {len(matches)} matches.",
            file=sys.stderr,
        )
        return None

    try:
        await client.get_thread(raw)
        return raw
    except Exception:
        return None


async def run_query(prompt: str, mode: str, thread_id: str | None = None) -> int:
    if thread_id:
        settings.thread_id = thread_id
    conn = await _connect()
    if conn is None:
        return 1
    client, session = conn

    out = Output(mode)
    engine = _Engine(out)
    session.messages.append({"role": "user", "content": prompt})

    try:
        await engine.consume(
            client.stream_message(session.thread_id, session.assistant_id, prompt),
            StreamState(),
        )
        interrupt = await engine.handle_interrupts(client, session)
    except Exception as e:  # noqa: BLE001
        print(f"Stream error: {e}", file=sys.stderr)
        return 1

    await _upsert(client, session, prompt)
    out.finalize(
        thread_id=session.thread_id,
        graph_id=session.graph_id,
        answer=engine.answer,
        interrupt=interrupt,
    )
    return 2 if interrupt is not None else 0


async def run_resume(thread_id_arg: str, message: str | None, mode: str) -> int:
    probe = AgentClient(url=settings.langgraph_url, api_key=settings.langsmith_api_key)
    _route_render_to_stderr()
    resolved = await _resolve_thread_id(probe, thread_id_arg)
    if resolved is None:
        print(f"Thread '{thread_id_arg}' not found.", file=sys.stderr)
        return 1

    settings.thread_id = resolved
    conn = await _connect(probe)
    if conn is None:
        return 1
    client, session = conn

    out = Output(mode)
    engine = _Engine(out)

    try:
        thread_state = await client.get_thread_state(session.thread_id)
        pending = extract_interrupts(thread_state)
    except Exception:
        pending = []

    try:
        if pending:
            # The thread is paused on an interrupt — resume it. A tool approval
            # is auto-approved; a question is answered with the supplied message
            # (the whole point of the printed resume hint). No message + a
            # question → nothing to answer with, so abort.
            interrupt0 = pending[0]
            if _is_hitl_middleware_interrupt(interrupt0.value):
                resume_value = build_resume_value(interrupt0, "approve", None)
            elif message:
                resume_value = build_resume_value(interrupt0, message, None)
            else:
                await _upsert(client, session, "(resumed)")
                out.finalize(
                    thread_id=session.thread_id,
                    graph_id=session.graph_id,
                    answer="",
                    interrupt=interrupt0,
                )
                return 2
            await engine.consume(
                client.resume(session.thread_id, session.assistant_id, resume_value),
                StreamState(),
            )
        else:
            if not message:
                print(
                    'A message is required: deepagent resume <id> "your message"',
                    file=sys.stderr,
                )
                return 1
            session.messages.append({"role": "user", "content": message})
            await engine.consume(
                client.stream_message(session.thread_id, session.assistant_id, message),
                StreamState(),
            )

        interrupt = await engine.handle_interrupts(client, session)
    except Exception as e:  # noqa: BLE001
        print(f"Stream error: {e}", file=sys.stderr)
        return 1

    await _upsert(client, session, message or "(resumed)")
    out.finalize(
        thread_id=session.thread_id,
        graph_id=session.graph_id,
        answer=engine.answer,
        interrupt=interrupt,
    )
    return 2 if interrupt is not None else 0


async def run_list() -> int:
    rows = await list_threads(limit=50)
    print_thread_list(rows)
    return 0
