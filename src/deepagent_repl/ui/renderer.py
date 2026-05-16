from __future__ import annotations

import difflib

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

import deepagent_repl.ui.theme as _theme
from deepagent_repl.handlers.interrupt import InterruptInfo
from deepagent_repl.handlers.tools import FormattedToolCall, FormattedToolResult
from deepagent_repl.ui.markdown import render_markdown

console = Console()

# ASCII art logo — compact pixel-art style agent face
_LOGO_LINES = [
    "     ) (   )  (  (",
    "     ( )  (    ) )",
    "     _____________",
    "    (_____________) ___",
    "    |             |/ _ \\",
    "    |               | | |",
    "    |               |_| |",
    " ___|             |\\___/",
    "/    \\___________/    \\",
    "\\_____________________/",
]


def render_header(
    graph_id: str | None = None,
    server_url: str | None = None,
    thread_id: str | None = None,
    num_skills: int = 0,
) -> None:
    """Render a styled startup header with logo and connection info."""
    # Build info lines to place next to logo
    info_lines: list[tuple[str, str]] = []

    # Line 1: graph name (bold)
    info_lines.append(("bold white", graph_id or "deepagent"))

    # Line 2: server URL
    if server_url:
        info_lines.append(("dim", server_url))

    # Line 3: thread + skills count
    meta_parts = []
    if thread_id:
        tid_short = thread_id[:12] + "…" if len(thread_id) > 12 else thread_id
        meta_parts.append(f"thread {tid_short}")
    if num_skills > 0:
        meta_parts.append(f"{num_skills} skill{'s' if num_skills != 1 else ''}")
    if meta_parts:
        info_lines.append((f"dim {_theme.ACCENT_COLOR}", " · ".join(meta_parts)))

    # Vertically center info next to logo
    pad_top = max(0, (len(_LOGO_LINES) - len(info_lines)) // 2)

    console.print()
    for i, logo_line in enumerate(_LOGO_LINES):
        row = Text()
        row.append(logo_line, style=f"bold {_theme.ACCENT_COLOR}")
        row.append("  ", style="")  # gap between logo and info

        info_idx = i - pad_top
        if 0 <= info_idx < len(info_lines):
            style, text = info_lines[info_idx]
            row.append(text, style=style)

        console.print(row)


class StreamingRenderer:
    """Manages live-updating display during streaming responses.

    While streaming, renders the accumulated buffer as Rich Markdown so that
    syntax highlighting and formatting appear in real time. A spinner is shown
    until the first token arrives.
    """

    def __init__(self):
        self._live: Live | None = None
        self._buffer: str = ""
        self._has_content: bool = False

    def start(self) -> None:
        """Start the live display with a waiting spinner."""
        self._buffer = ""
        self._has_content = False
        self._live = Live(
            Spinner("dots", text="Thinking...", style="dim"),
            console=console,
            refresh_per_second=10,
            transient=True,
            vertical_overflow="visible",
        )
        self._live.start()

    def update(self, text_fragment: str) -> None:
        """Append a text fragment and refresh the display with markdown rendering."""
        if not self._live:
            return
        self._buffer += text_fragment
        self._has_content = True
        md = render_markdown(self._buffer)
        cursor = Text("\u258b", style="bold green")
        self._live.update(Group(md, cursor))

    def finish(self) -> str:
        """Stop the live display and return the accumulated text.

        The live region is transient, so it vanishes on stop. The caller
        should print the final content if needed.
        """
        if self._live:
            self._live.stop()
            self._live = None
        result = self._buffer
        self._buffer = ""
        return result

    @property
    def has_content(self) -> bool:
        return self._has_content


def render_user_message(text: str) -> None:
    """Visually separate the user's turn from the agent's response."""
    if not text.strip():
        return


def render_assistant_text(text: str) -> None:
    """Render assistant response text as formatted markdown."""
    if text.strip():
        console.print()  # spacing before response
        console.print(render_markdown(text))


def render_tool_call(tc: FormattedToolCall) -> None:
    """Render a tool call via the shared widget registry."""
    from deepagent_repl.ui.tool_widgets import render_tool_call_widget

    console.print(render_tool_call_widget(tc))


def render_tool_running(name: str) -> None:
    """Render a spinner indicating a tool is executing."""
    console.print(Spinner("dots", text=f"  Running {name}...", style="dim"))


def render_tool_result(result: FormattedToolResult) -> None:
    """Render a tool result via the shared widget registry."""
    from deepagent_repl.ui.tool_widgets import render_tool_result_widget

    console.print(render_tool_result_widget(result))

    # Detect and render any image paths in the tool result
    if not result.is_error and result.content:
        from deepagent_repl.utils.images import detect_image_paths

        for img_path in detect_image_paths(result.content):
            render_image(img_path)


def _render_edit_file_panel(interrupt: InterruptInfo) -> None:
    """Render an edit_file interrupt as a coloured diff view."""
    args_dict: dict = {}
    if isinstance(interrupt.value, dict):
        for ar in interrupt.value.get("action_requests", []):
            if isinstance(ar.get("args"), dict):
                args_dict.update(ar["args"])

    file_path = args_dict.get("file_path", "")
    old_string = str(args_dict.get("old_string", ""))
    new_string = str(args_dict.get("new_string", ""))
    replace_all = args_dict.get("replace_all", False)

    body = Text()
    if file_path:
        body.append(f"{file_path}\n", style="bold")
    if replace_all:
        body.append("replace_all: True\n", style="dim yellow")

    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))

    if diff:
        body.append("\n")
        for line in diff[2:]:  # skip --- +++ headers
            if not line.endswith("\n"):
                line = line + "\n"
            if line.startswith("+"):
                body.append(line, style="green")
            elif line.startswith("-"):
                body.append(line, style="red")
            elif line.startswith("@@"):
                body.append(line, style=f"dim {_theme.ACCENT_COLOR}")
            else:
                body.append(line, style="dim")
    else:
        # Fallback: no diff (e.g. identical strings)
        body.append(new_string, style="dim")

    console.print(
        Panel(
            body,
            title=Text(" edit_file ", style="bold yellow"),
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
            expand=False,
        )
    )


def render_interrupt_panel(interrupt: InterruptInfo) -> None:
    """Render the interrupt panel only (no options line).

    Dispatches to a tool-specific renderer when available.
    """
    console.print()

    if interrupt.description == "edit_file":
        _render_edit_file_panel(interrupt)
        return

    # Generic panel: tool name + condensed arg lines
    desc = interrupt.description or "Action required"
    items: list[Text] = [Text(desc, style="bold")]

    args_dict: dict = {}
    if isinstance(interrupt.value, dict):
        for ar in interrupt.value.get("action_requests", []):
            if isinstance(ar.get("args"), dict):
                args_dict.update(ar["args"])
        if not args_dict and isinstance(interrupt.value.get("args"), dict):
            args_dict = interrupt.value["args"]

    for key, val in args_dict.items():
        val_str = str(val)
        if len(val_str) > 60:
            val_str = val_str[:57] + "..."
        items.append(Text(f"+ {key}  {val_str}", style="dim"))

    console.print(
        Panel(
            Group(*items),
            title=Text(" Interrupt ", style="bold yellow"),
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
            expand=False,
        )
    )


def render_interrupt(interrupt: InterruptInfo) -> None:
    """Render a pending interrupt with panel + static options line.

    Used for non-interactive (piped) contexts.
    """
    render_interrupt_panel(interrupt)

    # Options on a single line
    parts: list[Text] = []
    for i, option in enumerate(interrupt.options, 1):
        style = "bold green" if option in ("approve", "accept", "yes") else (
            "bold red" if option in ("reject", "deny", "no") else f"bold {_theme.ACCENT_COLOR}"
        )
        parts.append(Text(f"[{i}] {option}", style=style))
    line = Text("  ")
    for j, part in enumerate(parts):
        if j:
            line.append("  ")
        line.append_text(part)
    console.print(line)
    console.print()


def render_image(path: str) -> None:
    """Render an image — inline if terminal supports it, otherwise show file path."""
    from deepagent_repl.utils.images import can_render_inline, write_inline_image

    if can_render_inline():
        console.print()
        if write_inline_image(path):
            console.print(Text(f"  {path}", style="dim"))
            return

    # Fallback: show file path in a panel
    console.print(
        Panel(
            Text(path, style="bold"),
            title=Text(" Image ", style="bold blue"),
            title_align="left",
            border_style="blue",
            padding=(0, 1),
            expand=False,
        )
    )


def render_error(message: str) -> None:
    """Render an error message."""
    console.print(Text(f"Error: {message}", style="bold red"))


def render_shortcut_hint() -> None:
    """Render a hint below the header."""
    console.print(Text("  /help for available commands", style="dim"))


def render_info(message: str) -> None:
    """Render an informational message."""
    console.print(Text(message, style="dim"))
