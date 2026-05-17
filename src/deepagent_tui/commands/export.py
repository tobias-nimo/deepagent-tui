"""The /export and /copy commands — save or copy a conversation transcript."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def _build_transcript(messages: list[dict]) -> str:
    lines: list[str] = []

    for msg in messages:
        role = msg.get("role") or msg.get("type", "")
        content = _extract_text(msg.get("content", "")).strip()

        if role in ("user", "human"):
            if content:
                lines.append(f"❯  {content}")
                lines.append("")

        elif role in ("ai", "assistant"):
            if content:
                lines.append(content)
                lines.append("")

    return "\n".join(lines)


def _copy_to_clipboard(text: str) -> bool:
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


async def _resolve_workspace(client, session) -> Path:
    if session.workspace_root:
        return Path(session.workspace_root)
    try:
        skills = await client.get_skills_from_state(session.thread_id)
        for skill in skills:
            path = skill.get("path", "")
            if path:
                try:
                    root = Path(path).parents[3]
                    session.workspace_root = str(root)
                    return root
                except IndexError:
                    pass
    except Exception:
        pass
    return Path.cwd()


async def _fetch_messages(client, session) -> list[dict] | None:
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
        render_info("No messages to export.")
        return None
    return messages


@command("export", "Export conversation to .workspace/history/<thread_id>.md")
async def cmd_export(client, session, args: str) -> None:
    messages = await _fetch_messages(client, session)
    if messages is None:
        return

    transcript = _build_transcript(messages)

    workspace = await _resolve_workspace(client, session)
    path = workspace / "history" / f"{session.thread_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript)
    render_info(f"Conversation exported to {path}")


@command("copy", "Copy conversation to clipboard")
async def cmd_copy(client, session, args: str) -> None:
    messages = await _fetch_messages(client, session)
    if messages is None:
        return

    transcript = _build_transcript(messages)

    if _copy_to_clipboard(transcript):
        render_info("Conversation copied to clipboard.")
    else:
        render_error("Failed to copy to clipboard (install xsel, xclip, or wl-clipboard)")
