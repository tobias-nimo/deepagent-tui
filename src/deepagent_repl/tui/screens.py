from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from deepagent_repl.handlers.interrupt import InterruptInfo


class ApprovalScreen(ModalScreen[str | None]):
    """Modal dialog for HITL interrupt approval.

    Dismisses with the chosen option string, or None on Esc/cancel.
    """

    CSS = """
    ApprovalScreen { align: center middle; }
    #dialog {
        width: 70%;
        max-width: 90;
        height: auto;
        background: $panel;
        border: thick $warning;
        padding: 1 2;
    }
    #title { color: $warning; text-style: bold; padding-bottom: 1; }
    #detail { color: $text-muted; padding-bottom: 1; }
    OptionList { height: auto; max-height: 10; background: $panel; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, interrupt: InterruptInfo) -> None:
        super().__init__()
        self._interrupt = interrupt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._interrupt.description or "Action required", id="title")
            if self._interrupt.detail:
                detail = self._interrupt.detail
                if len(detail) > 400:
                    detail = detail[:400] + "..."
                yield Label(detail, id="detail")
            options = [Option(opt, id=opt) for opt in self._interrupt.options]
            yield OptionList(*options, id="options")

    def on_mount(self) -> None:
        self.query_one("#options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
