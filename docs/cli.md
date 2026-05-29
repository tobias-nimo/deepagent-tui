# CLI (headless mode)

`deepagent-tui` ships a second entry point, `deepagent`, for non-interactive use:
one-shot queries, scripting, and piping. It talks to the same LangGraph Deep Agent
server as the TUI and shares the same configuration — it's just headless. The TUI
(`deepagent-tui`) is unchanged; `deepagent` is a separate command.

```bash
deepagent query "summarize the repo"        # one-shot in a new thread
deepagent resume <thread_id> "and now..."   # continue a saved conversation
deepagent list                              # recent threads from the local index
deepagent --help                            # full usage (per-subcommand --help too)
```

## Subcommands

### `query <prompt>`

Runs a single turn in a **new** thread (or an existing one with `--thread`). Tool
calls are **auto-approved** — there's no human at the keyboard to confirm them. On
exit it prints a `deepagent resume <id>` command so you can pick the conversation
back up later (in the CLI or the TUI).

```bash
deepagent query "list the open TODOs in this repo"
echo "explain the error in build.log" | deepagent query -   # prompt from stdin
deepagent query "..." --thread 1f3a…                        # send into an existing thread
```

If the prompt is omitted or given as `-`, it's read from stdin.

### `resume <thread_id> [message]`

Continues a saved thread. The id can be a **full id or a unique prefix** — it's
resolved against the local index first, then the server. Behavior depends on the
thread's state:

- **Not paused** → `message` is required and is sent as the next turn.
- **Paused on a tool approval** → auto-approved; `message` is optional.
- **Paused on a question** → `message` answers the question and the run continues.
  Without a message, the run aborts and reprints the question (exit code 2).

```bash
deepagent resume 1f3a "and now write the tests"
deepagent resume 1f3a            # continue a thread that's paused on a tool approval
```

### `list`

Prints the recent threads recorded in `~/.deepagent-tui/threads.db` (the same index
that powers the TUI's `/resume`) as a plain table: short id, last-updated time,
graph, message count, and the last message. Use it to find an id for `resume`.

When `GRAPH_ID` is pinned (env var or `--graph`), the list is scoped to that agent;
with no graph pinned it shows threads from every agent.

## Flags

Shared by `query` and `resume`:

| Flag | Description |
|------|-------------|
| `--url URL` | Override `LANGGRAPH_URL` for this invocation |
| `--graph GRAPH_ID` | Override `GRAPH_ID` (pin a specific assistant) |
| `--quiet` | Print only the final answer on stdout (no streaming or tool lines) |
| `--json` | Emit a single structured JSON object instead of text |
| `--thread ID` | (`query` only) send into an existing thread instead of creating one |

All [environment variables](configuration.md) still apply; flags override them.

## Output and piping

By default (`live` mode) the streams are split so the command composes in a shell:

- **stdout** — the assistant's answer, streamed as it arrives.
- **stderr** — tool-call lines (`▸ read_file(path=…)`), result markers, and the
  `Resume:` hint.

So you can keep just the answer:

```bash
deepagent query "what does main() do?" 2>/dev/null > answer.txt
```

`--quiet` suppresses the live progress and prints only the final answer (still on
stdout, hint on stderr). `--json` prints a single object on stdout and keeps it
clean — connection and discovery messages are routed to stderr:

```bash
deepagent query "list the files" --json | jq -r .response
```

JSON shape:

```json
{
  "thread_id": "1f3a…",
  "graph_id": "jarvis",
  "response": "…",
  "tool_calls": ["read_file(path=README.md)", "grep(pattern=def main)"],
  "interrupted": false,
  "resume_command": "deepagent resume 1f3a… \"<your next message>\""
}
```

When a run aborts on a question, `interrupted` is `true` and the object also carries
`question` and `options`.

## Interrupts and auto-approve

`query` (and `resume` continuing a run) auto-approve **tool** interrupts — i.e. the
[human-in-the-loop](hitl.md) tool-approval prompts you'd otherwise confirm in the
TUI. A **non-tool** interrupt (an agent asking a free-form question with its own
options) has no safe default answer in a headless run, so the command **aborts**,
prints the question and a `deepagent resume` hint, and exits `2`. Answer it with
`deepagent resume <id> "<answer>"`.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Configuration, connection, or thread-lookup error |
| `2` | Aborted awaiting human input (a non-tool interrupt) |

## See also

- [Configuration](configuration.md) — the env vars `--url`/`--graph` override
- [Threads](threads.md) — the local index, `/resume`, `/rewind`, `/copy`, `/export`
- [HITL approvals](hitl.md) — what "tool interrupt" means and the TUI counterpart
