# Human-in-the-loop

How the TUI handles tool calls that pause the run for approval.

## When the agent pauses

> Which tool calls are gated server-side (e.g. `edit_file`), how the interrupt arrives over the SDK, what the TUI does with it.

## The approval widget

> Inline rendering, diff vs. argument summary, keyboard flow (number key, arrows + Enter, Esc to reject).

## After a decision

> What happens on approve, what happens on reject, retry behavior, how multiple interrupts in a single turn are sequenced.

## Implementation pointers

> Files involved: `tui/inline_approval.py`, `handlers/interrupt.py`. Where the decision is sent back to the server.
