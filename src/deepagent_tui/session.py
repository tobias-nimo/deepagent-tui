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
    total_cost: float = 0.0
    messages: list[dict] = field(default_factory=list)
    prompt_session: Any = None  # PromptSession instance (set during startup)
    picker: Any = None  # async (options: list[str], title: str | None) -> str | None — set by TUI
    replay: Any = None  # async (messages: list[dict]) -> None — set by TUI to clear and re-render past messages on /resume
    show_help: Any = None  # async () -> None — set by TUI; pushes the help screen
    show_commands: Any = None  # async () -> None — set by TUI; pushes the commands screen
    show_status: Any = None  # async () -> None — set by TUI; pushes the status screen
    show_settings: Any = None  # async () -> None — set by TUI; pushes the settings screen
    set_input: Any = None  # (text: str) -> None — set by TUI; fills the chat input bar and focuses it
    discovered_tools: dict[str, str] = field(default_factory=dict)  # name -> description
    discovered_skills_from_state: bool = False  # True once skills_metadata fetched from thread
    workspace_root: str | None = None  # DEEPAGENT_WORKSPACE env var, else server thread state
    hitl_enabled: bool = True  # when False, /settings auto-approves HITL interrupts
    tool_widget_mode: str = "expanded"  # "expanded" or "condensed"; see ui/tool_widgets.py

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate token usage and recompute cost."""
        from deepagent_tui.utils.cost import compute_cost

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_cost += compute_cost(input_tokens, output_tokens, self.model)
