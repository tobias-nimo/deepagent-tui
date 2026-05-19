"""Setup helpers used by the TUI on startup: discover an assistant on the
configured LangGraph server, create or attach to a thread, and register the
agent's skills as dynamic slash commands.
"""

from __future__ import annotations

from deepagent_tui.client import AgentClient
from deepagent_tui.commands import clear_dynamic, register_skill
from deepagent_tui.config import settings
from deepagent_tui.session import Session
from deepagent_tui.ui.renderer import render_error, render_info


async def connect(client: AgentClient, session: Session) -> bool:
    """Discover an assistant on the server, attach the session to a thread.

    Returns True on success. Failures (no server, no matching graph_id,
    ambiguous selection with no resolver) are reported via the rich
    console — the TUI captures that output and replays it inline.
    """
    try:
        assistants = await client.discover_assistants()
    except Exception as e:
        render_error(f"Cannot connect to {settings.langgraph_url}: {e}")
        return False

    if not assistants:
        render_error("No assistants found on server.")
        return False

    if settings.graph_id:
        matches = [a for a in assistants if a["graph_id"] == settings.graph_id]
        if not matches:
            available = ", ".join(a["graph_id"] for a in assistants)
            render_error(f"Graph '{settings.graph_id}' not found. Available: {available}")
            return False
        assistant = matches[0]
    elif len(assistants) == 1:
        assistant = assistants[0]
    else:
        # Multiple assistants and no GRAPH_ID set — the REPL used to prompt
        # interactively here; the TUI hasn't grown a picker for this case
        # yet, so fall through to the first assistant and surface the list
        # as info so the user can pin one via env var.
        render_info("Multiple assistants found — defaulting to the first one:")
        for a in assistants:
            render_info(f"  · {a['graph_id']} (id: {a['assistant_id'][:8]}…)")
        render_info("Set GRAPH_ID to pin a specific graph.")
        assistant = assistants[0]

    session.assistant_id = assistant["assistant_id"]
    session.graph_id = assistant["graph_id"]

    if settings.thread_id:
        session.thread_id = settings.thread_id
    else:
        session.thread_id = await client.create_thread()

    # Intentionally don't persist the thread to the local index here. The
    # first user message will upsert it via the stream worker — if the user
    # never sends a message, this thread shouldn't occupy a retention slot.
    return True


def register_skill_command(name: str, desc: str, path: str) -> None:
    """Register a skill name so /<name> appears in autocomplete and
    `dynamic_commands()`. The handler is intentionally a no-op — the TUI
    routes skill invocations through its own streaming worker instead of
    calling the registered handler (see DeepAgentTUI._run_command)."""
    del path  # kept in the signature for symmetry with discovery payloads

    async def _noop(_client, _session, _args: str) -> None:
        return

    register_skill(name, desc, _noop)


async def discover_and_register_skills(client: AgentClient, session: Session) -> None:
    """Pull skills from server-side assistant metadata and register each as
    a dynamic slash command. Best-effort — silent on failure."""
    clear_dynamic()

    if not session.assistant_id:
        return

    try:
        skills = await client.discover_skills(session.assistant_id)
    except Exception:
        skills = []

    for skill in skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        path = skill.get("path", "")
        if not name:
            continue
        register_skill_command(name, desc, path)

    if skills:
        render_info(
            f"Discovered {len(skills)} skill(s) from server metadata. Type /skills to list."
        )
