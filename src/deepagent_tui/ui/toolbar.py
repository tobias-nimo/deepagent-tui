"""Bottom toolbar for the REPL prompt — shows session info at a glance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit.formatted_text import HTML

import deepagent_tui.ui.theme as _theme

if TYPE_CHECKING:
    from deepagent_tui.session import Session


def create_toolbar(session: "Session"):
    """Return a bottom_toolbar callback that reads live session state."""

    def _toolbar() -> HTML:
        # Left: graph + thread
        graph = session.graph_id or "—"
        tid = session.thread_id or "—"
        tid_short = tid[:8] if len(tid) > 8 else tid
        left = f" {graph} │ {tid_short}"

        # Center: status
        _status_map: dict[str, tuple[str, str]] = {
            "idle": ("", "idle"),
            "streaming": (_theme.accent_ptk().replace("fg:", ""), "streaming..."),
            "interrupted": ("ansiyellow", "waiting for approval"),
        }
        style, label = _status_map.get(session.status, ("", session.status))
        if style:
            center = f"<{style}>{label}</{style}>"
        else:
            center = label

        # Right: tokens + cost
        from deepagent_tui.utils.cost import format_cost, format_tokens

        in_tok = format_tokens(session.input_tokens)
        out_tok = format_tokens(session.output_tokens)
        cost = format_cost(session.total_cost)
        right = f"{in_tok}↑ {out_tok}↓ │ {cost} "

        return HTML(
            f"<style bg='#1a1a2e' fg='#aaaaaa'>"
            f"{left}"
            f"  │  {center}"
            f"  │  {right}"
            f"</style>"
        )

    return _toolbar
