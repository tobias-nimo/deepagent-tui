"""Headless command-line interface for deepagent-tui.

The TUI (`deepagent-tui`) is unchanged; this is a separate `deepagent`
entry point for scripting and one-shot use. Subcommands: `query`, `resume`,
`list`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from deepagent_tui.config import add_connection_flags, apply_connection_overrides

_DESCRIPTION = """\
Headless client for a LangGraph Deep Agent server.

Examples:
  deepagent query "summarize the repo"        run a one-shot query
  echo "explain this" | deepagent query -     read the prompt from stdin
  deepagent query "..." --quiet               print only the final answer
  deepagent query "..." --json                emit a structured JSON object
  deepagent resume <thread_id> "and now..."   continue a saved conversation
  deepagent list                              list recent local threads

Output (live, the default): assistant text -> stdout, tool activity and the
resume hint -> stderr, so `deepagent query "x" 2>/dev/null` yields just the
answer. Exit codes: 0 ok, 1 error, 2 aborted awaiting human input.
"""


def _add_output_flags(p: argparse.ArgumentParser) -> None:
    """The mutually-exclusive output-mode flags shared by `query` and `resume`."""
    out = p.add_mutually_exclusive_group()
    out.add_argument(
        "--quiet",
        action="store_true",
        help="print only the final answer on stdout (no streaming/tool lines)",
    )
    out.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit a single JSON object (thread_id, response, tool_calls, ...)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepagent",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    q = sub.add_parser(
        "query",
        help="run a one-shot query in a new (or targeted) thread",
        description="Run a one-shot query. Tool calls are auto-approved. "
        "Reads the prompt from the argument, or from stdin if it is omitted "
        'or given as "-".',
    )
    q.add_argument(
        "prompt",
        nargs="?",
        help='the prompt to send; omit or pass "-" to read from stdin',
    )
    add_connection_flags(q, thread=True)
    _add_output_flags(q)

    r = sub.add_parser(
        "resume",
        help="continue a saved conversation by thread id",
        description="Continue a saved thread. Accepts a full id or a unique "
        "prefix. If the thread is paused on a tool approval it is "
        "auto-approved; if paused on a question, the message answers it.",
    )
    r.add_argument("thread_id", help="full thread id or a unique prefix")
    r.add_argument(
        "message",
        nargs="?",
        help="message to send (required unless the thread is mid-interrupt)",
    )
    add_connection_flags(r, thread=False)
    _add_output_flags(r)

    sub.add_parser(
        "list",
        help="list recent threads from the local index",
        description="List recent threads recorded in ~/.deepagent-tui/threads.db.",
    )

    return parser


def _output_mode(args: argparse.Namespace) -> str:
    if getattr(args, "as_json", False):
        return "json"
    if getattr(args, "quiet", False):
        return "quiet"
    return "live"


def _read_prompt(raw: str | None) -> str | None:
    """Resolve the prompt: explicit text, or stdin when omitted/`-`."""
    if raw is None or raw == "-":
        data = sys.stdin.read().strip()
        return data or None
    return raw


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Import lazily so `--help` and arg errors stay fast and dependency-light.
    from deepagent_tui.cli import runner

    if args.command == "list":
        sys.exit(asyncio.run(runner.run_list()))

    apply_connection_overrides(args)  # url/graph/thread → settings
    mode = _output_mode(args)

    if args.command == "query":
        prompt = _read_prompt(args.prompt)
        if not prompt:
            parser.error("query: no prompt given (argument or stdin)")
        sys.exit(asyncio.run(runner.run_query(prompt, mode)))

    if args.command == "resume":
        message = args.message
        if message == "-":
            message = sys.stdin.read().strip() or None
        sys.exit(asyncio.run(runner.run_resume(args.thread_id, message, mode)))

    parser.print_help()
    sys.exit(0)
