from __future__ import annotations

import difflib
from typing import Callable

from rich.console import Group, RenderableType
from rich.text import Text

import deepagent_repl.ui.theme as _theme
from deepagent_repl.handlers.tools import FormattedToolCall, FormattedToolResult

# Trace markers. Plain unicode glyphs (not emoji) so width stays predictable
# across the CLI and Textual rendering paths.
_MARKER = "●"
_SUBAGENT_MARKER = "◈"
_OK_MARKER = "✓"
_ERR_MARKER = "✗"
_INDENT = "  "

# Cap on inline-rendered Write content; longer files get a "+N more lines"
# trailer so the trace doesn't explode.
_MAX_WRITE_LINES = 20


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
    marker: str = _MARKER,
    marker_style: str | None = None,
) -> Text:
    style = marker_style or _accent()
    out = Text()
    out.append(f"{marker} ", style=f"bold {style}")
    out.append(tool, style=f"bold {style}")
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
        "list_files": "ls",
        "list_directory": "ls",
    }
    return aliases.get(n, n)


def _build_diff(old: str, new: str) -> Text | None:
    old_lines = old.splitlines() or [""]
    new_lines = new.splitlines() or [""]
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    if not diff:
        return None
    out = Text()
    accent = _accent()
    first = True
    for line in diff[2:]:  # skip --- / +++ headers
        if not first:
            out.append("\n")
        first = False
        if line.startswith("+"):
            out.append(line, style="green")
        elif line.startswith("-"):
            out.append(line, style="red")
        elif line.startswith("@@"):
            out.append(line, style=f"dim {accent}")
        else:
            out.append(line, style="dim")
    return out


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


def _call_edit(tc: FormattedToolCall) -> RenderableType:
    a = tc.args
    file_path = a.get("file_path") or a.get("path") or ""
    old_string = str(a.get("old_string", ""))
    new_string = str(a.get("new_string", ""))
    replace_all = a.get("replace_all", False)

    summary = Text()
    if file_path:
        summary.append(file_path, style="dim")
    if replace_all:
        if summary.plain:
            summary.append("  ", style="dim")
        summary.append("(replace_all)", style="dim yellow")

    header = _header("Edit", summary if summary.plain else None)
    diff = _build_diff(old_string, new_string)
    if diff is None:
        return header
    return Group(header, _indent_block(diff))


def _call_write(tc: FormattedToolCall) -> RenderableType:
    a = tc.args
    file_path = a.get("file_path") or a.get("path") or ""
    content = str(a.get("content") or a.get("file_text") or "")

    header = _header("Write", file_path if file_path else None)
    if not content:
        return header

    lines = content.splitlines()
    shown = lines[:_MAX_WRITE_LINES]
    body = Text()
    for i, line in enumerate(shown):
        if i:
            body.append("\n")
        body.append("+ " + line, style="green")
    extra = len(lines) - len(shown)
    if extra > 0:
        body.append("\n")
        body.append(f"… +{extra} more line{'s' if extra != 1 else ''}", style="dim")
    return Group(header, _indent_block(body))


def _call_read(tc: FormattedToolCall) -> RenderableType:
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
    return _header("Read", summary if summary.plain else None)


def _call_grep(tc: FormattedToolCall) -> RenderableType:
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
    return _header("Grep", summary if summary.plain else None)


def _call_glob(tc: FormattedToolCall) -> RenderableType:
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
    return _header("Glob", summary if summary.plain else None)


def _call_bash(tc: FormattedToolCall) -> RenderableType:
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
    return _header("Bash", summary if summary.plain else None)


def _call_ls(tc: FormattedToolCall) -> RenderableType:
    a = tc.args
    path = a.get("path") or a.get("directory") or "."
    return _header("ls", str(path))


def _call_write_todos(tc: FormattedToolCall) -> RenderableType:
    a = tc.args
    todos = a.get("todos") or a.get("items") or []
    if not isinstance(todos, list):
        return _header("write_todos", "(invalid)")

    count = len(todos)
    header = _header(
        "write_todos",
        f"{count} item{'s' if count != 1 else ''}",
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


def _call_subagent(tc: FormattedToolCall) -> RenderableType:
    name = tc.subagent_name or tc.name or "subagent"
    input_str = tc.subagent_input or ""
    header = Text()
    header.append(f"{_SUBAGENT_MARKER} ", style="bold magenta")
    header.append(f"subagent: {name}", style="bold magenta")
    if input_str:
        header.append("  ")
        header.append(_short(input_str, 100), style="dim")
    return header


def _call_generic(tc: FormattedToolCall) -> RenderableType:
    args_text = _format_args(tc.args)
    return _header(tc.name, args_text if args_text else None)


_CALL_RENDERERS: dict[str, Callable[[FormattedToolCall], RenderableType]] = {
    "edit": _call_edit,
    "write": _call_write,
    "read": _call_read,
    "grep": _call_grep,
    "glob": _call_glob,
    "bash": _call_bash,
    "ls": _call_ls,
    "write_todos": _call_write_todos,
}


def render_tool_call_widget(tc: FormattedToolCall) -> RenderableType:
    """Dispatch a tool call to its per-tool widget renderer."""
    if tc.is_subagent:
        return _call_subagent(tc)
    renderer = _CALL_RENDERERS.get(_tool_alias(tc.name))
    if renderer is None:
        return _call_generic(tc)
    return renderer(tc)


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


def _result_read(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    content = result.content or ""
    n_lines = content.count("\n") + (1 if content else 0)
    header = _result_header(error=False)
    header.append(f"{n_lines} line{'s' if n_lines != 1 else ''}", style="dim")
    return header


def _result_grep(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    matches = [ln for ln in (result.content or "").splitlines() if ln.strip()]
    n = len(matches)
    header = _result_header(error=False)
    if n == 0:
        header.append("no matches", style="dim")
        return header
    header.append(f"{n} match{'es' if n != 1 else ''}", style="dim")
    preview = matches[:4]
    if not preview:
        return header
    body = Text()
    for i, ln in enumerate(preview):
        if i:
            body.append("\n")
        body.append(_short(ln, 100), style="dim")
    remaining = n - len(preview)
    if remaining > 0:
        body.append("\n")
        body.append(f"… (+{remaining} more)", style="dim")
    return Group(header, _indent_block(body, indent=_INDENT * 2))


def _result_edit(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    header = _result_header(error=False)
    header.append("applied", style="dim")
    return header


def _result_write(result: FormattedToolResult, call) -> RenderableType:
    if result.is_error:
        return _result_inline(result.summary, error=True)
    header = _result_header(error=False)
    header.append("saved", style="dim")
    return header


def _result_bash(result: FormattedToolResult, call) -> RenderableType:
    error = result.is_error
    if not result.content:
        header = _result_header(error=error)
        header.append("failed" if error else "done", style="dim")
        return header
    body = _truncate_body(result.content)
    return _result_with_body("output", body, error=error)


def _result_generic(result: FormattedToolResult, call) -> RenderableType:
    error = result.is_error
    content = result.content or ""
    if not content:
        header = _result_header(error=error)
        header.append("failed" if error else "done", style="dim")
        return header
    if "\n" not in content and len(content) <= 100:
        return _result_inline(content, error=error)
    body = _truncate_body(content)
    return _result_with_body("output", body, error=error)


_RESULT_RENDERERS: dict[
    str, Callable[[FormattedToolResult, FormattedToolCall | None], RenderableType]
] = {
    "edit": _result_edit,
    "write": _result_write,
    "read": _result_read,
    "grep": _result_grep,
    "glob": _result_grep,
    "bash": _result_bash,
    "ls": _result_bash,
}


def render_tool_result_widget(
    result: FormattedToolResult,
    call: FormattedToolCall | None = None,
) -> RenderableType:
    """Dispatch a tool result to its per-tool widget renderer."""
    name = _tool_alias(call.name if call else result.name)
    renderer = _RESULT_RENDERERS.get(name)
    if renderer is None:
        return _result_generic(result, call)
    return renderer(result, call)
