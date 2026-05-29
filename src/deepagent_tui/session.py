from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    """Mutable session state for the current REPL run."""

    thread_id: str | None = None
    graph_id: str | None = None
    assistant_id: str | None = None
    model: str | None = None
    status: str = "idle"  # idle | streaming | interrupted
    input_tokens: int = 0
    output_tokens: int = 0
    # Input tokens reported on the most recent single model call — used as a
    # proxy for "current context fill" by the /settings Usage meter. Cumulative
    # `input_tokens` would grow forever and exceed the window even when each
    # turn is small (e.g. after compaction).
    last_input_tokens: int = 0
    total_cost: float = 0.0
    # Optional metadata exposed by server-side middleware (agent_info,
    # llm_info). Each is None/empty when the middleware isn't attached, and
    # the /settings panel degrades gracefully.
    tools: list[str] = field(default_factory=list)
    subagents: list[str] = field(default_factory=list)
    context_window: int | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    messages: list[dict] = field(default_factory=list)
    prompt_session: Any = None  # PromptSession instance (set during startup)
    picker: Any = None  # async (options: list[str], title: str | None) -> str | None — set by TUI
    replay: Any = None  # async (messages: list[dict]) -> None — set by TUI to clear and re-render past messages on /resume
    show_help: Any = None  # async () -> None — set by TUI; pushes the help screen
    show_settings: Any = None  # async () -> None — set by TUI; pushes the settings screen
    set_input: Any = None  # (text: str) -> None — set by TUI; fills the chat input bar and focuses it
    exit_app: Any = None  # () -> None — set by TUI; cleanly stops the app so run() returns (used by /exit)
    rerender_tool_widgets: Any = None  # () -> None — set by TUI; re-renders existing tool widgets after /settings flips the widget mode
    rerender_assistant_messages: Any = None  # () -> None — set by TUI; re-renders existing assistant messages after /settings flips the Markdown toggle
    discovered_tools: dict[str, str] = field(default_factory=dict)  # name -> description
    discovered_skills_from_state: bool = False  # True once skills_metadata fetched from thread
    workspace_root: str | None = None  # reported by the server in thread state
    hitl_enabled: bool = True  # when False, /settings auto-approves HITL interrupts
    tool_widget_mode: str = "default"  # "compacted" | "default" | "expanded"; see ui/tool_widgets.py
    markdown_enabled: bool = True  # when False, assistant chunks render as raw text (debug aid)
    language: str = "english"  # static for now; placeholder for future i18n
    thinking_animation: str = "braille"  # which "Thinking…" animation to play; see ui/thinking.py

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate token usage and (when prices are known) cost.

        Cost only accrues when `llm_info_middleware` has populated
        `input_price_per_mtok` / `output_price_per_mtok` on thread state.
        Without those, `total_cost` stays at 0 and surfaces should render
        a "middleware not attached" hint rather than the false zero.
        """
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if (
            self.input_price_per_mtok is not None
            and self.output_price_per_mtok is not None
        ):
            self.total_cost += (
                input_tokens * self.input_price_per_mtok
                + output_tokens * self.output_price_per_mtok
            ) / 1_000_000
