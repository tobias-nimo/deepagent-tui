from __future__ import annotations

import ast
import difflib
import os
from typing import Callable

from rich.console import Group, RenderableType
from rich.text import Text

import deepagent_repl.ui.theme as _theme
from deepagent_repl.handlers.tools import FormattedToolCall, FormattedToolResult

# Trace markers. Plain unicode glyphs (not emoji) so width stays predictable
# across the CLI and Textual rendering paths.
_MARKER = "●"
_PENDING_MARKER = "○"
_OK_MARKER = "✓"
_ERR_MARKER = "✗"
_INDENT = "  "
_SUBAGENT_PROGRESS_MAX = 3


def _state_marker(state: str) -> tuple[str, str]:
    """Map a call state to (glyph, rich style) for the header marker."""
    if state == "success":
        return _MARKER, "#1a7f37"
    if state == "error":
        return _MARKER, "#9a2a2a"
    return _PENDING_MARKER, "dim"

def _accent() -> str:
    return _theme.ACCENT_COLOR


def _short(value, max_len: int = 60) -> str:
    s = str(value).replace("\n", " ").strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _indent_block(body: Text, indent: str = _INDENT) -> Text:
    """Prefix every line of body with `indent`, preserving inline styles."""
    lines = body.split("\n")
    out = Text()
    for i, ln in enumerate(lines):
        if i:
            out.append("\n")
        out.append(indent)
        out.append_text(ln)
    return out


def _header(
    tool: str,
    summary: Text | str | None = None,
    *,
    state: str = "pending",
    marker: str | None = None,
    marker_style: str | None = None,
) -> Text:
    glyph, style = _state_marker(state)
    if marker is not None:
        glyph = marker
    if marker_style is not None:
        style = marker_style
    out = Text()
    out.append(f"{glyph} ", style=f"bold {style}")
    out.append(tool, style="bold white")
    if summary is not None:
        out.append("  ")
        if isinstance(summary, str):
            out.append(summary, style="dim")
        else:
            out.append_text(summary)
    return out


def _tool_alias(name: str) -> str:
    """Normalize a tool name so different naming conventions land on the same
    renderer (e.g. `edit_file` and `str_replace_editor` both map to `edit`)."""
    n = (name or "").lower()
    aliases = {
        "edit_file": "edit",
        "str_replace_editor": "edit",
        "write_file": "write",
        "create_file": "write",
        "read_file": "read",
        "open_file": "read",
        "todo_write": "write_todos",
        "todowrite": "write_todos",
        "shell": "bash",
        "run_shell": "bash",
        "run_command": "bash",
        "execute": "bash",
        "list_files": "ls",
        "list_directory": "ls",
    }
    return aliases.get(n, n)


def _format_args(args: dict, max_total: int = 120) -> str:
    if not args:
        return ""
    parts: list[str] = []
    total = 0
    for key, val in args.items():
        val_str = str(val).replace("\n", " ").strip()
        if len(val_str) > 60:
            val_str = val_str[:57] + "…"
        part = f"{key}={val_str}"
        total += len(part)
        if total > max_total and parts:
            parts.append("…")
            break
        parts.append(part)
    return ", ".join(parts)


# ── Per-tool call renderers ───────────────────────────────────────────────


def _call_edit(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    file_path = a.get("file_path") or a.get("path") or ""
    replace_all = a.get("replace_all", False)
    summary = Text()
    if file_path:
        summary.append(file_path, style="dim")
    if replace_all:
        if summary.plain:
            summary.append("  ", style="dim")
        summary.append("(replace_all)", style="dim yellow")
    return _header("Edit", summary if summary.plain else None, state=state)


def _call_write(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    file_path = a.get("file_path") or a.get("path") or ""
    return _header("Write", file_path if file_path else None, state=state)


def _call_read(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    file_path = a.get("file_path") or a.get("path") or ""
    offset = a.get("offset")
    limit = a.get("limit")
    summary = Text()
    if file_path:
        summary.append(file_path, style="dim")
    if offset is not None or limit is not None:
        bits: list[str] = []
        if offset is not None:
            bits.append(f"offset={offset}")
        if limit is not None:
            bits.append(f"limit={limit}")
        if summary.plain:
            summary.append("  ", style="dim")
        summary.append("(" + ", ".join(bits) + ")", style="dim")
    return _header("Read", summary if summary.plain else None, state=state)


def _call_grep(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    pattern = a.get("pattern") or a.get("regex") or a.get("query") or ""
    path = a.get("path") or a.get("directory") or ""
    glob = a.get("glob") or a.get("include") or ""
    summary = Text()
    if pattern:
        summary.append('"', style="dim")
        summary.append(_short(str(pattern), 60), style=f"dim {_accent()}")
        summary.append('"', style="dim")
    if path:
        summary.append("  in ", style="dim")
        summary.append(str(path), style="dim")
    if glob:
        summary.append("  (", style="dim")
        summary.append(str(glob), style="dim")
        summary.append(")", style="dim")
    return _header("Search", summary if summary.plain else None, state=state)


def _call_glob(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    pattern = a.get("pattern") or a.get("glob") or ""
    path = a.get("path") or a.get("directory") or ""
    summary = Text()
    if pattern:
        summary.append(str(pattern), style=f"dim {_accent()}")
    if path:
        if summary.plain:
            summary.append("  in ", style="dim")
        summary.append(str(path), style="dim")
    return _header("Find", summary if summary.plain else None, state=state)


def _call_bash(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    command = str(a.get("command") or a.get("cmd") or a.get("shell") or "")
    description = str(a.get("description") or "")
    summary = Text()
    if command:
        summary.append(_short(command, 100), style=f"dim {_accent()}")
    if description:
        if summary.plain:
            summary.append("  · ", style="dim")
        summary.append(description, style="dim")
    return _header("Bash", summary if summary.plain else None, state=state)


def _call_ls(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    path = a.get("path") or a.get("directory") or "."
    return _header("List", str(path), state=state)


def _call_write_todos(tc: FormattedToolCall, state: str) -> RenderableType:
    a = tc.args
    todos = a.get("todos") or a.get("items") or []
    if not isinstance(todos, list):
        return _header("write_todos", "(invalid)", state=state)

    count = len(todos)
    header = _header(
        "write_todos",
        f"{count} item{'s' if count != 1 else ''}",
        state=state,
    )
    if not todos:
        return header

    body = Text()
    first = True
    for todo in todos:
        if not first:
            body.append("\n")
        first = False
        if isinstance(todo, dict):
            status = str(todo.get("status") or "").lower()
            content = (
                todo.get("content")
                or todo.get("text")
                or todo.get("title")
                or todo.get("task")
                or ""
            )
        else:
            status = ""
            content = str(todo)
        if status == "completed":
            box, style = "✓", "dim green"
        elif status in ("in_progress", "doing", "active", "running"):
            box, style = "◐", f"bold {_accent()}"
        elif status in ("cancelled", "skipped"):
            box, style = "—", "dim strike"
        else:
            box, style = "○", "dim"
        body.append(f"{box} ", style=style)
        body.append(str(content), style=style)
    return Group(header, _indent_block(body))


def _progress_summary(tc: FormattedToolCall) -> tuple[str, str]:
    """One-line (tool_name, short_summary) for an inner subagent tool call.
    Used to render minimal `⎿ Bash  ls -la` style progress under the parent
    Subagent widget — no result body, no per-tool formatting."""
    a = tc.args
    alias = _tool_alias(tc.name)
    if alias == "bash":
        return ("Bash", _short(str(a.get("command") or a.get("cmd") or ""), 80))
    if alias == "edit":
        return ("Edit", str(a.get("file_path") or a.get("path") or ""))
    if alias == "write":
        return ("Write", str(a.get("file_path") or a.get("path") or ""))
    if alias == "read":
        return ("Read", str(a.get("file_path") or a.get("path") or ""))
    if alias == "grep":
        return ("Search", _short(str(a.get("pattern") or a.get("query") or ""), 60))
    if alias == "glob":
        return ("Find", _short(str(a.get("pattern") or a.get("glob") or ""), 60))
    if alias == "ls":
        return ("List", str(a.get("path") or a.get("directory") or ""))
    if alias == "write_todos":
        items = a.get("todos") or a.get("items") or []
        n = len(items) if isinstance(items, list) else 0
        return ("write_todos", f"{n} item{'s' if n != 1 else ''}")
    return (tc.name, _format_args(tc.args, max_total=80))


def _render_progress_body(progress: list[tuple[str, str]]) -> Text:
    # Rolling window: only the most recent N entries are shown. When a new
    # inner tool fires the oldest visible line drops off the top so the widget
    # height stays bounded for long-running subagents.
    shown = progress[-_SUBAGENT_PROGRESS_MAX:]
    body = Text()
    for i, (name, summary) in enumerate(shown):
        if i:
            body.append("\n")
        body.append("⎿ ", style="dim")
        body.append(name, style="bold dim")
        if summary:
            body.append("  ")
            body.append(summary, style="dim")
    return body


def _call_subagent(
    tc: FormattedToolCall,
    state: str,
    *,
    progress: list[tuple[str, str]] | None = None,
) -> RenderableType:
    subagent_type = str(tc.args.get("subagent_type") or "")
    header = _header(
        "Subagent",
        subagent_type if subagent_type else None,
        state=state,
    )
    if not progress:
        return header
    return Group(header, _indent_block(_render_progress_body(progress)))


def _call_generic(tc: FormattedToolCall, state: str) -> RenderableType:
    args_text = _format_args(tc.args)
    return _header(tc.name, args_text if args_text else None, state=state)


_CALL_RENDERERS: dict[str, Callable[[FormattedToolCall, str], RenderableType]] = {
    "edit": _call_edit,
    "write": _call_write,
    "read": _call_read,
    "grep": _call_grep,
    "glob": _call_glob,
    "bash": _call_bash,
    "ls": _call_ls,
    "write_todos": _call_write_todos,
}


def render_tool_call_widget(
    tc: FormattedToolCall,
    state: str = "pending",
    *,
    progress: list[tuple[str, str]] | None = None,
) -> RenderableType:
    """Dispatch a tool call to its per-tool widget renderer.

    `state` controls the leading marker: "pending" → `○` dim, "success" → `●`
    green, "error" → `●` red. `progress` is only used by the subagent
    renderer to append `⎿` lines for inner tool calls observed in the
    subagent's subgraph stream.
    """
    if tc.is_subagent:
        return _call_subagent(tc, state, progress=progress)
    renderer = _CALL_RENDERERS.get(_tool_alias(tc.name))
    if renderer is None:
        return _call_generic(tc, state)
    return renderer(tc, state)


# ── Per-tool result renderers ─────────────────────────────────────────────


def _result_header(*, error: bool) -> Text:
    style = "red" if error else "green"
    marker = _ERR_MARKER if error else _OK_MARKER
    out = Text()
    out.append(_INDENT)
    out.append(f"{marker} ", style=f"bold {style}")
    return out


def _result_inline(text: str, *, error: bool) -> Text:
    header = _result_header(error=error)
    header.append(_short(text, 120), style="dim")
    return header


def _result_with_body(summary: str, body: Text, *, error: bool) -> Group:
    header = _result_header(error=error)
    header.append(summary, style="dim")
    return Group(header, _indent_block(body, indent=_INDENT * 2))


def _truncate_body(content: str, max_lines: int = 8, max_chars: int = 600) -> Text:
    lines = content.splitlines()
    shown = lines[:max_lines]
    body = Text()
    used = 0
    last = len(shown) - 1
    for i, ln in enumerate(shown):
        if used + len(ln) > max_chars:
            ln = ln[: max(0, max_chars - used - 1)] + "…"
            body.append(ln, style="dim")
            body.append("\n")
            remaining = len(lines) - i
            if remaining > 0:
                body.append(
                    f"… (+{remaining} more line{'s' if remaining != 1 else ''})",
                    style="dim",
                )
            return body
        body.append(ln, style="dim")
        if i != last:
            body.append("\n")
        used += len(ln) + 1
    extra = len(lines) - len(shown)
    if extra > 0:
        body.append("\n")
        body.append(
            f"… (+{extra} more line{'s' if extra != 1 else ''})",
            style="dim",
        )
    return body


def _corner_inline(text: str) -> Text:
    """Inline result line prefixed by the `⎿` corner marker (dim)."""
    out = Text()
    out.append(_INDENT)
    out.append("⎿ ", style="dim")
    out.append(text, style="dim")
    return out


def _match_count_text(n: int) -> str:
    if n == 0:
        return "No matches found"
    if n == 1:
        return "1 match"
    return f"{n} matches"


def _result_read(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    content = result.content or ""
    n_lines = content.count("\n") + (1 if content else 0)
    return _corner_inline(f"{n_lines} line{'s' if n_lines != 1 else ''}")


def _result_grep(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    content = (result.content or "").strip()
    # The grep tool reports an empty hit set with a free-form sentence rather
    # than empty content, so count those as zero before we split into lines.
    lower = content.lower()
    if (
        not content
        or lower.startswith("no matches")
        or lower.startswith("no results")
    ):
        n = 0
    else:
        n = sum(1 for ln in content.splitlines() if ln.strip())
    return _corner_inline(_match_count_text(n))


def _result_glob(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    # Find returns a Python list literal — parse it instead of counting lines.
    matches = _parse_listing(result.content or "")
    return _corner_inline(_match_count_text(len(matches)))


# Dim-on-dark backgrounds for diff lines, plus solid marker colours. Hex so
# truecolor terminals render them consistently and 256-colour fall-backs map
# to a close neighbour rather than ANSI red/green at full intensity.
_DIFF_BG_ADD = "#0e2718"
_DIFF_BG_DEL = "#2c1414"
_DIFF_FG_ADD = "#2ea043"
_DIFF_FG_DEL = "#f85149"
_DIFF_MAX_LINES = 7


def _build_diff_lines(old: str, new: str) -> list[tuple[str, str]]:
    """Unified diff broken into (kind, text) pairs where kind ∈ {'+', '-', ' '}.
    Drops the file-header (`---` / `+++`) and hunk (`@@`) lines so the caller
    can format each line itself."""
    old_lines = old.splitlines() or [""]
    new_lines = new.splitlines() or [""]
    raw = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))
    out: list[tuple[str, str]] = []
    for line in raw:
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            out.append(("+", line[1:]))
        elif line.startswith("-"):
            out.append(("-", line[1:]))
        else:
            out.append((" ", line[1:] if line.startswith(" ") else line))
    return out


def _added_removed_summary(added: int, removed: int) -> str:
    if not added and not removed:
        return "no changes"
    parts: list[str] = []
    if added:
        parts.append(f"Added {added} line{'s' if added != 1 else ''}")
    if removed:
        word = "removed" if added else "Removed"
        parts.append(f"{word} {removed} line{'s' if removed != 1 else ''}")
    return ", ".join(parts)


def _render_diff_body(diff_lines: list[tuple[str, str]]) -> Text:
    """Render diff hunks with `+`/`-` markers and a dim background, capped at
    `_DIFF_MAX_LINES`; trailing overflow is summarised as `… (+N more)`."""
    shown = diff_lines[:_DIFF_MAX_LINES]
    body = Text()
    for i, (kind, text) in enumerate(shown):
        if i:
            body.append("\n")
        if kind == "+":
            body.append("+ ", style=f"bold {_DIFF_FG_ADD} on {_DIFF_BG_ADD}")
            body.append(text, style=f"on {_DIFF_BG_ADD}")
        elif kind == "-":
            body.append("- ", style=f"bold {_DIFF_FG_DEL} on {_DIFF_BG_DEL}")
            body.append(text, style=f"on {_DIFF_BG_DEL}")
        else:
            body.append("  ", style="dim")
            body.append(text, style="dim")
    extra = len(diff_lines) - len(shown)
    if extra > 0:
        body.append("\n")
        body.append(f"… (+{extra} more line{'s' if extra != 1 else ''})", style="dim")
    return body


def _corner_block_with_summary(summary: str, body: Text) -> Text:
    """⎿ summary on the corner line; `body` lines align under the summary."""
    out = Text()
    out.append(_INDENT)
    out.append("⎿ ", style="dim")
    out.append(summary, style="dim")
    if not body.plain:
        return out
    align = _INDENT + "  "
    for line in body.split("\n"):
        out.append("\n")
        out.append(align)
        out.append_text(line)
    return out


def _result_edit(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    if call is None:
        return _corner_inline("applied")
    old_string = str(call.args.get("old_string", ""))
    new_string = str(call.args.get("new_string", ""))
    diff_lines = _build_diff_lines(old_string, new_string)
    if not diff_lines:
        return _corner_inline("applied")
    added = sum(1 for k, _ in diff_lines if k == "+")
    removed = sum(1 for k, _ in diff_lines if k == "-")
    return _corner_block_with_summary(
        _added_removed_summary(added, removed),
        _render_diff_body(diff_lines),
    )


def _result_write(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    if call is None:
        return _corner_inline("saved")
    content = str(call.args.get("content") or call.args.get("file_text") or "")
    if not content:
        return _corner_inline("saved")
    lines = content.splitlines() or [""]
    n = len(lines)
    summary = f"Added {n} line{'s' if n != 1 else ''}"
    shown = lines[:_DIFF_MAX_LINES]
    body = Text()
    for i, line in enumerate(shown):
        if i:
            body.append("\n")
        body.append("+ ", style=f"bold {_DIFF_FG_ADD} on {_DIFF_BG_ADD}")
        body.append(line, style=f"on {_DIFF_BG_ADD}")
    extra = n - len(shown)
    if extra > 0:
        body.append("\n")
        body.append(f"… (+{extra} more line{'s' if extra != 1 else ''})", style="dim")
    return _corner_block_with_summary(summary, body)


def _corner_block(body: Text) -> Text:
    """Render `body` under a `⎿` corner marker. First line sits next to the
    corner; subsequent lines align beneath that first line. Inline styles on
    `body` are preserved."""
    out = Text()
    out.append(_INDENT)
    out.append("⎿ ", style="dim")
    align = _INDENT + "  "
    for i, ln in enumerate(body.split("\n")):
        if i:
            out.append("\n")
            out.append(align)
        out.append_text(ln)
    return out


def _strip_bash_trailer(content: str) -> str:
    """Drop the `[Command succeeded/failed with exit code N]` trailer that the
    bash tool appends to its output. The exit status is already encoded in the
    result marker, so the line is redundant noise in the trace."""
    lines = content.rstrip().splitlines()
    while lines:
        last = lines[-1].strip()
        if (
            last.startswith("[Command succeeded")
            or last.startswith("[Command failed")
        ) and last.endswith("]"):
            lines.pop()
            continue
        if not last:
            lines.pop()
            continue
        break
    return "\n".join(lines)


def _result_bash(result: FormattedToolResult, call) -> RenderableType:
    error = result.is_error
    content = _strip_bash_trailer(result.content or "")
    if not content:
        header = _result_header(error=error)
        header.append("failed" if error else "done", style="dim")
        return header
    body = _truncate_body(content)
    return _corner_block(body)


def _parse_listing(content: str) -> list[str]:
    """Best-effort parse of an `ls`-style result. Handles Python/JSON list
    literals (`['a', 'b']`) as well as plain newline-separated output."""
    s = (content or "").strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            value = ast.literal_eval(s)
            if isinstance(value, (list, tuple)):
                return [str(x) for x in value]
        except (ValueError, SyntaxError):
            pass
    entries: list[str] = []
    for line in s.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if ln.startswith("- "):
            ln = ln[2:]
        entries.append(ln)
    return entries


def _basename(path: str) -> str:
    """Filename component, preserving the trailing `/` for directories."""
    p = path.strip()
    trailing = "/" if p.endswith("/") else ""
    name = os.path.basename(p.rstrip("/")) or p
    return name + trailing


def _result_ls(result: FormattedToolResult, call) -> RenderableType:
    """Compact directory listing: ⎿ first entry, up to 5 entries, then …"""
    if result.is_error:
        return _result_inline(result.summary, error=True)
    names = [_basename(e) for e in _parse_listing(result.content or "")]
    out = Text()
    out.append(_INDENT)
    out.append("⎿ ", style="dim")
    if not names:
        out.append("(empty)", style="dim")
        return out

    max_entries = 5
    shown = names[:max_entries]
    align = _INDENT + "  "  # align continuation lines with the first entry
    for i, entry in enumerate(shown):
        if i:
            out.append("\n")
            out.append(align)
        out.append(entry, style="dim")
    if len(names) > max_entries:
        remaining = len(names) - max_entries
        out.append("\n")
        out.append(align)
        out.append(f"… (+{remaining} more)", style="dim")
    return out


def _result_generic(result: FormattedToolResult, call) -> RenderableType:
    # Use the corner marker for both success and error — the call widget's
    # green/red `●` already conveys outcome, so a ✓/✗ here would be redundant.
    content = result.content or ""
    if not content:
        return _corner_inline("failed" if result.is_error else "done")
    if "\n" not in content and len(content) <= 100:
        return _corner_inline(content)
    body = _truncate_body(content, max_lines=_DIFF_MAX_LINES)
    return _corner_block(body)


def _result_task(result: FormattedToolResult, call) -> RenderableType | None:
    """Subagent results are suppressed: the parent agent re-summarises the
    subagent's output in its own next turn, so re-printing the raw return
    value is redundant. The accumulated `⎿` progress lines on the call
    widget already show what the subagent did."""
    return None


_RESULT_RENDERERS: dict[
    str,
    Callable[
        [FormattedToolResult, FormattedToolCall | None], RenderableType | None
    ],
] = {
    "edit": _result_edit,
    "write": _result_write,
    "read": _result_read,
    "grep": _result_grep,
    "glob": _result_glob,
    "bash": _result_bash,
    "ls": _result_ls,
    "task": _result_task,
}


def render_tool_result_widget(
    result: FormattedToolResult,
    call: FormattedToolCall | None = None,
) -> RenderableType | None:
    """Dispatch a tool result to its per-tool widget renderer. Returns `None`
    when the tool opts out of result rendering (currently only the subagent
    `task` tool)."""
    name = _tool_alias(call.name if call else result.name)
    renderer = _RESULT_RENDERERS.get(name)
    if renderer is None:
        return _result_generic(result, call)
    return renderer(result, call)
