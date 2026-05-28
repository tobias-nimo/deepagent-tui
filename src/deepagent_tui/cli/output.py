"""Terminal/JSON output for the headless CLI.

Three modes:
- ``live``  — assistant text streams to stdout; tool activity and the resume
  hint go to stderr, so ``deepagent query "x" 2>/dev/null`` yields just the
  answer.
- ``quiet`` — nothing during the run; the final answer prints to stdout at the
  end, the resume hint to stderr.
- ``json``  — one structured object to stdout; nothing to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepagent_tui.handlers.interrupt import InterruptInfo
    from deepagent_tui.handlers.tools import FormattedToolResult


def resume_command(thread_id: str, message: str = "<your next message>") -> str:
    """The shell command that continues this thread."""
    return f'deepagent resume {thread_id} "{message}"'


class Output:
    """Emits run progress and the final result according to the chosen mode."""

    def __init__(self, mode: str = "live") -> None:
        self.mode = mode
        self.tool_summaries: list[str] = []

    # --- streaming surface (only live mode writes during the run) ---

    def stream_text(self, frag: str) -> None:
        if self.mode == "live":
            sys.stdout.write(frag)
            sys.stdout.flush()

    def tool_call(self, summary: str) -> None:
        self.tool_summaries.append(summary)
        if self.mode == "live":
            print(f"▸ {summary}", file=sys.stderr, flush=True)

    def tool_result(self, result: FormattedToolResult) -> None:
        if self.mode == "live":
            marker = "✗" if result.is_error else "⎿"
            print(f"  {marker} {result.summary}", file=sys.stderr, flush=True)

    # --- final emission ---

    def finalize(
        self,
        *,
        thread_id: str,
        graph_id: str | None,
        answer: str,
        interrupt: InterruptInfo | None = None,
    ) -> None:
        """Emit the final result. ``interrupt`` set means the run aborted
        awaiting human input (a non-tool interrupt)."""
        if self.mode == "json":
            self._emit_json(thread_id, graph_id, answer, interrupt)
            return

        # live: a streamed answer has no trailing newline; quiet: print it now.
        if self.mode == "quiet":
            if answer:
                sys.stdout.write(answer)
        if answer and not answer.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

        if interrupt is not None:
            print(
                f"\n⚠ Agent needs input: {interrupt.description}",
                file=sys.stderr,
            )
            if interrupt.options:
                print(f"   options: {', '.join(interrupt.options)}", file=sys.stderr)

        print(f"\nResume: {resume_command(thread_id)}", file=sys.stderr, flush=True)

    def _emit_json(
        self,
        thread_id: str,
        graph_id: str | None,
        answer: str,
        interrupt: InterruptInfo | None,
    ) -> None:
        payload = {
            "thread_id": thread_id,
            "graph_id": graph_id,
            "response": answer,
            "tool_calls": self.tool_summaries,
            "interrupted": interrupt is not None,
            "resume_command": resume_command(thread_id),
        }
        if interrupt is not None:
            payload["question"] = interrupt.description
            payload["options"] = interrupt.options
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_thread_list(rows: list[dict]) -> None:
    """Print recent threads (from the local DB) as a plain table to stdout."""
    if not rows:
        print("No saved threads.", file=sys.stderr)
        return

    header = f"{'THREAD':<10}  {'UPDATED':<19}  {'GRAPH':<16}  {'MSGS':>4}  LAST MESSAGE"
    print(header)
    for r in rows:
        tid = (r.get("id") or "")[:8]
        updated = (r.get("updated_at") or "")[:19]
        graph = (r.get("graph_id") or "")[:16]
        msgs = r.get("message_count") or 0
        last = " ".join((r.get("last_message") or "").split())
        if len(last) > 50:
            last = last[:47] + "..."
        print(f"{tid:<10}  {updated:<19}  {graph:<16}  {msgs:>4}  {last}")
