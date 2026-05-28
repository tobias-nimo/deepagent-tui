# Key bindings

The TUI has three keybinding contexts — the main app, the inline approval prompt, and the picker screen (`/resume`, `/rewind`, `/skills`). Each one captures keys directly, so behavior depends on what's currently in focus.

## Main app

### Editing the message

| Key | Action |
|-----|--------|
| `Enter` | Submit the message |
| `Shift+Enter` / `Alt+Enter` / `Ctrl+J` | Insert a newline |
| `↑` / `↓` | Move the cursor within a multi-line message |
| `↑` on the first line | Recall the previous (older) submitted message into the input bar |
| `↓` on the last line | Recall the next (newer) message, or restore your in-progress draft once you step past the newest |

Recall walks the history of messages you've submitted this session (consecutive duplicates collapsed). Whatever you'd typed before pressing `↑` is stashed and comes back when you `↓` past the newest entry. Recall stays bound to the arrows even when a recalled `/command` re-opens the autocomplete, so navigation isn't trapped by the menu. Plain arrows no longer scroll the transcript — use `PgUp` / `PgDn` (below) for that.

### Autocomplete

The autocomplete popup serves two input prefixes (see [input.md](input.md)):

- `/` at the start of a single-line message → slash-command matches (hides if you insert a newline).
- `@token` anywhere in a message → workspace file-path matches (keyed off the cursor, so it works mid-message).

| Key | Action |
|-----|--------|
| `Tab` | Insert the highlighted entry — a command (followed by a space), or a file path |
| `Esc` | Hide the autocomplete |
| Click | Selects an option |

For `@`, inserting a directory keeps the menu open so you can drill in; inserting a file closes it.

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

`/resume`, `/rewind`, and `/skills` open a full-screen picker.

| Key | Action |
|-----|--------|
| Any printable character | Append to the search query; results re-filter live |
| `Backspace` / `Ctrl+H` | Delete the last query character |
| `↑` / `↓` / `Ctrl+P` / `Ctrl+N` / `Tab` / `Shift+Tab` | Move the selection |
| `Enter` | Select the highlighted item |
| `Esc` / `Ctrl+C` | Cancel and return without selecting |

## Help screen

`/help` opens a full-screen help view (static content, no selection).

| Key | Action |
|-----|--------|
| `↑` / `↓` / `j` / `k` | Scroll by one line |
| `PgUp` / `PgDn` | Scroll by a page |
| `Esc` / `Ctrl+C` / `q` | Close |

## Settings screen

`/settings` opens a four-tab modal (Config / Harness / Usage / Status).

| Key | Action |
|-----|--------|
| `Shift+Tab` / `[` | Previous tab |
| `Tab` / `]` | Next tab |
| `↑` / `↓` / `k` / `j` | Move highlight (Config tab only) |
| `←` / `→` / `h` / `l` / `Space` | Cycle the selected row's value (Config tab only) |
| `Esc` / `Ctrl+C` / `q` | Close |

`Tab` and `Shift+Tab` only reach the settings screen if your terminal forwards them past the app's autocomplete priority binding — `[` and `]` always work as fallbacks.

## Terminal caveats

`Shift+Enter` requires the terminal to forward the modifier as a distinct keycode. These terminals are known to support it:

- Kitty
- Ghostty
- WezTerm
- iTerm2 — with **"Report modifiers using CSI u"** enabled in Settings → Profiles → Keys

When `Shift+Enter` doesn't work in your terminal, fall back to `Alt+Enter` or `Ctrl+J`, which work everywhere.
