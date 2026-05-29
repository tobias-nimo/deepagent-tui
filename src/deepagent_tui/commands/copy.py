"""The /copy command — copy the last assistant turn to the clipboard."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from deepagent_tui.commands import command
from deepagent_tui.ui.renderer import render_error, render_info


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b["text"] if isinstance(b, dict) and b.get("type") == "text" else str(b)
            for b in content
        ]
        return "\n".join(parts)
    return str(content)


def _yaml_scalar(value, indent: int = 0) -> str:
    """Render a value as a YAML scalar.

    Multiline values use a literal block (``|``) indented past their key by
    ``indent`` spaces; single-line values are single-quoted.
    """
    text = "" if value is None else str(value)
    if "\n" in text:
        pad = " " * (indent + 2)
        body = "\n".join(pad + line for line in text.splitlines())
        return "|\n" + body
    return "'" + text.replace("'", "''") + "'"


def _format_tool_block(tc: dict, result_msg: dict | None) -> str:
    name = tc.get("name", "unknown")
    args = tc.get("args", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            args = {"input": args} if args else {}
    if not isinstance(args, dict):
        args = {}

    lines = ["```yaml", f"tool: {_yaml_scalar(name)}"]
    if args:
        lines.append("parameters:")
        for key, value in args.items():
            lines.append(f"    - {key}: {_yaml_scalar(value, indent=4)}")
    if result_msg is not None:
        result = _extract_text(result_msg.get("content", "")).strip()
        lines.append(f"output: {_yaml_scalar(result)}")
    lines.append("```")
    return "\n".join(lines)


def _render_messages(messages: list[dict], *, include_users: bool) -> str:
    results_by_id: dict[str, dict] = {}
    for msg in messages:
        role = msg.get("role") or msg.get("type", "")
        if role == "tool":
            results_by_id[msg.get("tool_call_id", "")] = msg

    blocks: list[str] = []
    for msg in messages:
        role = msg.get("role") or msg.get("type", "")
        if role in ("user", "human"):
            if not include_users:
                continue
            content = _extract_text(msg.get("content", "")).strip()
            if content:
                lines = content.split("\n")
                formatted = "\n".join(
                    [f"❯  {lines[0]}", *(f"   {ln}" for ln in lines[1:])]
                )
                blocks.append(formatted)
        elif role in ("ai", "assistant"):
            content = _extract_text(msg.get("content", "")).strip()
            if content:
                blocks.append(content)
            for tc in msg.get("tool_calls") or []:
                blocks.append(_format_tool_block(tc, results_by_id.get(tc.get("id", ""))))
    return "\n\n".join(blocks)


def build_last_turn(messages: list[dict]) -> str:
    """Render the assistant turn after the most recent user message."""
    last_user_idx = -1
    for i, msg in enumerate(messages):
        role = msg.get("role") or msg.get("type", "")
        if role in ("user", "human"):
            last_user_idx = i
    return _render_messages(messages[last_user_idx + 1 :], include_users=False)


def build_full_transcript(messages: list[dict]) -> str:
    """Render the complete conversation including user messages and tool activity."""
    return _render_messages(messages, include_users=True)


def copy_to_clipboard(text: str) -> bool:
    encoded = text.encode()
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=encoded, check=True)
            return True
        if sys.platform == "win32":
            subprocess.run(["clip"], input=encoded, check=True)
            return True

        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if wayland:
            try:
                subprocess.run(["wl-copy"], input=encoded, check=True)
                return True
            except FileNotFoundError:
                pass

        try:
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=encoded, check=True, capture_output=True,
            )
            return True
        except FileNotFoundError:
            pass

        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.stdin.write(encoded)
            proc.stdin.close()
            return True
        except FileNotFoundError:
            pass

    except Exception:
        pass
    return False


async def fetch_messages(client, session) -> list[dict] | None:
    if not session.thread_id:
        render_error("No active thread.")
        return None
    try:
        state = await client.get_thread_state(session.thread_id)
    except Exception as e:
        render_error(f"Failed to fetch thread state: {e}")
        return None
    messages = state.get("values", {}).get("messages", [])
    if not messages:
        render_info("No messages to copy.")
        return None
    return messages


@command("copy", "Copy the last agent response to clipboard")
async def cmd_copy(client, session, args: str) -> None:
    messages = await fetch_messages(client, session)
    if messages is None:
        return

    transcript = build_last_turn(messages)
    if not transcript.strip():
        render_info("No agent response to copy yet.")
        return

    if copy_to_clipboard(transcript):
        render_info("Last response copied to clipboard.")
    else:
        render_error("Failed to copy to clipboard (install xsel, xclip, or wl-clipboard)")
