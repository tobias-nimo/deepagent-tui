from __future__ import annotations

import json
from dataclasses import dataclass

# Tool names that indicate subagent/task delegation
SUBAGENT_TOOL_NAMES = {"task", "delegate", "create_task", "spawn_agent"}


@dataclass
class FormattedToolCall:
    """A parsed and formatted tool call ready for display."""

    id: str
    name: str
    args: dict
    is_subagent: bool = False
    subagent_name: str | None = None
    subagent_input: str | None = None

    @property
    def summary(self) -> str:
        """One-line summary of the tool call."""
        if self.is_subagent and self.subagent_name:
            label = f"[subagent] {self.subagent_name}"
            if self.subagent_input:
                label += f": {_truncate(self.subagent_input, 60)}"
            return label
        parts = []
        for key, val in self.args.items():
            parts.append(f"{key}={_truncate(str(val), 40)}")
        arg_str = ", ".join(parts) if parts else ""
        if arg_str:
            return f"{self.name}({arg_str})"
        return self.name


@dataclass
class FormattedToolResult:
    """A parsed tool result ready for display."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False

    @property
    def summary(self) -> str:
        """Truncated one-line summary of the result."""
        return _truncate(self.content, 200)


def format_tool_call(raw: dict) -> FormattedToolCall:
    """Parse a raw tool call dict into a FormattedToolCall."""
    tc_id = raw.get("id", "")
    name = raw.get("name", "unknown")
    args = raw.get("args", {})

    # Parse args if they're a JSON string
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            args = {"input": args} if args else {}

    is_subagent = name in SUBAGENT_TOOL_NAMES
    subagent_name = None
    subagent_input = None

    if is_subagent and isinstance(args, dict):
        # Try common patterns for subagent delegation
        subagent_name = (
            args.get("agent_name")
            or args.get("name")
            or args.get("agent")
            or args.get("worker")
        )
        subagent_input = (
            args.get("input")
            or args.get("message")
            or args.get("instructions")
            or args.get("task")
        )
        if isinstance(subagent_input, dict):
            subagent_input = json.dumps(subagent_input, ensure_ascii=False)

    return FormattedToolCall(
        id=tc_id,
        name=name,
        args=args if isinstance(args, dict) else {},
        is_subagent=is_subagent,
        subagent_name=subagent_name,
        subagent_input=subagent_input,
    )


def format_tool_result(raw: dict) -> FormattedToolResult:
    """Parse a raw tool message dict into a FormattedToolResult."""
    from deepagent_tui.handlers.stream import extract_text_content

    name = raw.get("name", "tool")
    content = extract_text_content(raw.get("content", ""))
    is_error = raw.get("status") == "error"
    tool_call_id = raw.get("tool_call_id", "")

    return FormattedToolResult(
        tool_call_id=tool_call_id,
        name=name,
        content=content,
        is_error=is_error,
    )


def _truncate(text: str, max_len: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
