# Input bar

The chat bar at the bottom is where you talk to the agent. Most input is sent as-is, but a leading character switches it into a different mode. The welcome banner advertises them as `/ for commands · @ for file paths · ! shell mode`, and the hint bar above the chat bar reflects the current mode as you type.

## Plain messages

Anything that doesn't start with `/` or `!` is sent to the agent as a user message. `Enter` submits; `Shift+Enter` (or `Alt+Enter` / `Ctrl+J`) inserts a newline. `@file/path` tokens inside an otherwise-plain message are special — see the `@` file references section below.

## `/` — slash commands

Typing `/` at the start of a single-line message opens the command autocomplete. See [commands.md](commands.md) for the full list and [keybindings.md](keybindings.md#autocomplete) for the keys.

## `@` — file references

Type `@` anywhere in a message to browse the agent's workspace and drop a file path into your message. As you type after the `@`, an autocomplete dropdown lists matching files and directories:

- `Tab` (or a click) inserts the highlighted entry.
- Selecting a **directory** keeps the menu open so you can drill in; selecting a **file** inserts it with a trailing space and closes the menu.
- Entries are sorted directories-first, capped at 20. Dotfiles are hidden unless your query starts with `.`.
- The hint bar shows `Tab to insert file path` while an `@token` is active.

`@` must be the first character of a whitespace-delimited token, so `user@host` and email addresses don't trigger the picker.

### What the agent receives

On submit, every `@token` that resolves to an existing path under the workspace root is rewritten into a markdown link for the agent — `[name](abs path)` — while your message bubble shows a compact `@name`. Tokens that don't resolve to a real file (casual `@mentions`, typos) are left verbatim in both forms.

Paths are always resolved against the **agent's workspace root**, never the directory the TUI was launched from. The workspace root isn't known until the agent reports it, so before you've sent your first message the dropdown shows `Send a message first to load the workspace before browsing files` instead of a file list. See [server-middleware.md](server-middleware.md) for how the server exposes the workspace path.

## `!` — shell mode

A message that starts with `!` runs the rest of the line as a local shell command instead of being sent to the agent:

```
!git status
```

- The command runs through your `$SHELL -c` (falling back to `/bin/sh`) in the agent's workspace root.
- stdout and stderr are captured together and rendered inline under a dim `⎿` corner — dim on a zero exit, red on a non-zero exit. Output longer than 200 lines is truncated with a `… N more lines` footer.
- The command and its output are **local only** — neither is forwarded to the agent or added to the conversation it sees.
- Like `@`, shell mode needs the workspace root, so before your first message it prints `Send a message first to load the workspace before running shell commands.` instead of running.

The hint bar shows `Warning: shell mode activated` whenever the input starts with `!`.
