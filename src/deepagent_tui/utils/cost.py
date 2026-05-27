"""Formatters for token/cost display.

Cost arithmetic itself lives on `Session.add_usage` and only runs when the
server's `llm_info_middleware` has supplied per-token prices on thread state.
There's no hardcoded pricing table — surfaces that would otherwise show a
misleading "$0.0000" should check whether prices are available and hide the
cost field instead. See `docs/server-middleware.md`.
"""

from __future__ import annotations


def format_cost(cost: float) -> str:
    """Format a cost value for display."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def format_tokens(count: int) -> str:
    """Format a token count for compact display."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)
