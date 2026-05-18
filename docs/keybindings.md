# Key bindings

The TUI has three keybinding contexts — the main app, the inline approval prompt, and the picker screen (`/resume`, `/fork`). Each one captures keys directly, so behavior depends on what's currently in focus.

## Main app

### Editing the message

| Key | Action |
|-----|--------|
| `Enter` | Submit the message |
| `Shift+Enter` / `Alt+Enter` / `Ctrl+J` | Insert a newline |
| `↑` / `↓` | Move the cursor; at the top/bottom of the input, scroll the transcript by one line |

### Autocomplete

The autocomplete popup appears when you type `/` at the start of an empty message (single-line only — hides if you insert a newline).

| Key | Action |
|-----|--------|
| `Tab` | Insert the highlighted command followed by a space |
| `Esc` | Hide the autocomplete |
| Click | Selects an option |

### Stream / approval cancellation

`Esc` is overloaded; the first matching condition wins:

1. **Inline approval is showing** → rejects the approval (the run resumes with a reject decision).
2. **A response is streaming** → cancels the run, removes the in-flight UI (user message, tool widgets, partial assistant text), and restores your message into the input bar for editing.
3. **Autocomplete is open** → closes it.
4. **Pending image attachments exist** → clears them.

### Global

| Key | Action |
|-----|--------|
| `Ctrl+L` | Clear the message log (does not start a new thread; for that use `/new`) |
| `Ctrl+C` | Quit the TUI |
| `PgUp` / `PgDn` | Scroll the transcript by a page |

## Inline approval

When the agent calls a tool gated for approval, an inline approval widget mounts at the bottom of the transcript and takes focus. See [hitl.md](hitl.md) for the full flow.

| Key | Action |
|-----|--------|
| `1`–`9` | Select option N and confirm immediately |
| `↑` / `↓` / `Ctrl+P` / `Ctrl+N` / `Tab` / `Shift+Tab` | Move the highlight |
| `Enter` | Confirm the highlighted option |
| `Esc` / `Ctrl+C` | Cancel — equivalent to rejecting |

While the approval is showing, the chat bar and rules are hidden so the hint line is the last visible row.

## Picker screen

`/resume` and `/fork` open a full-screen picker.

| Key | Action |
|-----|--------|
| Any printable character | Append to the search query; results re-filter live |
| `Backspace` / `Ctrl+H` | Delete the last query character |
| `↑` / `↓` / `Ctrl+P` / `Ctrl+N` / `Tab` / `Shift+Tab` | Move the selection |
| `Enter` | Select the highlighted item |
| `Esc` / `Ctrl+C` | Cancel and return without selecting |

## Terminal caveats

`Shift+Enter` requires the terminal to forward the modifier as a distinct keycode. These terminals are known to support it:

- Kitty
- Ghostty
- WezTerm
- iTerm2 — with **"Report modifiers using CSI u"** enabled in Settings → Profiles → Keys

When `Shift+Enter` doesn't work in your terminal, fall back to `Alt+Enter` or `Ctrl+J`, which work everywhere.
