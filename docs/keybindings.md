# Key bindings

All keyboard shortcuts the TUI responds to, and the terminal caveats that affect some of them.

## Editing

> `Enter` to submit · `Shift+Enter` / `Alt+Enter` / `Ctrl+J` for newline · arrow keys for cursor and transcript scroll · `PgUp` / `PgDn`.

## Autocomplete

> `Tab` to complete · `↑` / `↓` to move within the popup · `Esc` to dismiss.

## Stream control

> `Esc` to cancel an in-flight stream and restore the message to the input · `Ctrl+L` to wipe the log · `Ctrl+C` to quit.

## Approval prompts

> Number keys · `↑` / `↓` + `Enter` · `Esc` to reject. Full flow in [hitl.md](hitl.md).

## Terminal caveats

> `Shift+Enter` requires the terminal to forward the modifier. Confirmed working: Kitty, Ghostty, WezTerm, iTerm2 (with "Report modifiers using CSI u" on). `Alt+Enter` and `Ctrl+J` always work as a fallback.
