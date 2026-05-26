"""Slash command registry and dispatcher.

Two-tier system:
  - **Built-in** commands are registered via the @command decorator at import time.
  - **Dynamic** commands are discovered from the connected server (skills) and
    registered at runtime via register_skill(). They are cleared on reconnect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from deepagent_tui.client import AgentClient
    from deepagent_tui.session import Session

CommandHandler = Callable[["AgentClient", "Session", str], Coroutine[Any, Any, None]]

# Registries are keyed by lowercased name so lookup is case-insensitive
# (`/HELP` and `/help` both resolve). The tuple carries the canonical name
# so listings and skill-invocation prompts preserve the original casing.
_builtin: dict[str, tuple[CommandHandler, str, str]] = {}
_dynamic: dict[str, tuple[CommandHandler, str, str]] = {}


def command(name: str, description: str = ""):
    """Decorator to register a built-in slash command handler."""

    def decorator(fn: CommandHandler) -> CommandHandler:
        _builtin[name.lower()] = (fn, description, name)
        return fn

    return decorator


def register_skill(name: str, description: str, handler: CommandHandler) -> None:
    """Register a server-discovered skill as a dynamic slash command."""
    _dynamic[name.lower()] = (handler, description, name)


def clear_dynamic() -> None:
    """Remove all dynamic commands (called before re-discovery on reconnect)."""
    _dynamic.clear()


def get_command(name: str) -> tuple[CommandHandler, str, str] | None:
    """Look up a command by name (case-insensitive).

    Built-in takes precedence over dynamic. Returns (handler, description,
    canonical_name) where canonical_name preserves the original casing used
    at registration.
    """
    key = name.lower()
    return _builtin.get(key) or _dynamic.get(key)


def all_commands() -> dict[str, str]:
    """Return {canonical_name: description} for all registered commands."""
    result = {canonical: desc for (_, desc, canonical) in _dynamic.values()}
    result.update({canonical: desc for (_, desc, canonical) in _builtin.values()})
    return result


def builtin_commands() -> dict[str, str]:
    """Return {canonical_name: description} for built-in commands only."""
    return {canonical: desc for (_, desc, canonical) in _builtin.values()}


def dynamic_commands() -> dict[str, str]:
    """Return {canonical_name: description} for dynamic (skill) commands only."""
    return {canonical: desc for (_, desc, canonical) in _dynamic.values()}


def is_dynamic(name: str) -> bool:
    """True if `name` (case-insensitive) is a registered dynamic skill command."""
    return name.lower() in _dynamic


def all_command_names() -> list[str]:
    """Return sorted list of all command names prefixed with /."""
    names = {canonical for (_, _, canonical) in _builtin.values()}
    names |= {canonical for (_, _, canonical) in _dynamic.values()}
    return sorted(f"/{n}" for n in names)


def is_command(text: str) -> bool:
    """Check if text starts with a slash command."""
    return text.startswith("/")


async def dispatch(client: "AgentClient", session: "Session", text: str) -> bool:
    """Dispatch a slash command. Returns True if handled, False if not a command."""
    if not is_command(text):
        return False

    parts = text[1:].split(None, 1)
    name = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    entry = get_command(name)
    if entry is None:
        # Forward unknown commands to the agent as skill invocations
        return False

    handler, _, _ = entry
    await handler(client, session, args)
    return True


# Side-effect imports — each module registers its handlers via the @command
# decorator at import time, populating `_builtin`. Kept at the bottom so the
# decorator and registry are defined before the modules try to use them.
from deepagent_tui.commands import (  # noqa: E402, F401
    builtins,
    compact,
    copy,
    export,
    help,
    new,
    resume,
    rewind,
    settings,
    skills,
    theme,
)
