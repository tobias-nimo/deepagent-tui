# Troubleshooting

Common failure modes and how to recover.

## "Cannot connect to <url>"

The TUI couldn't reach `LANGGRAPH_URL`. Check:

- Your LangGraph server is running. From the agent repo: `uv run langgraph dev --no-browser`
- `LANGGRAPH_URL` points to the right port (default `http://localhost:2024`)
- For LangGraph Cloud or remote servers, `LANGSMITH_API_KEY` is set

The TUI auto-exits 3 seconds after a failed connect so you can fix the env and re-launch.

## "No assistants found on server"

The server is up but `assistants.search()` returned nothing. This usually means the LangGraph project hasn't been built or registered. Re-run `langgraph dev` from the agent project root.

## "Multiple assistants found — defaulting to the first one"

There's no interactive picker for this case. The TUI uses the first assistant and prints all of them so you can pin one:

```bash
GRAPH_ID=my_agent uv run deepagent-tui
```

## "Graph '<id>' not found"

`GRAPH_ID` doesn't match any of the assistants the server exposes. The error includes the available graph ids — copy-paste the one you want.

## `Shift+Enter` inserts garbage instead of a newline

The terminal isn't forwarding the `Shift` modifier on `Enter`. Either:

- Switch to a terminal that supports it: Kitty, Ghostty, WezTerm
- In iTerm2: Settings → Profiles → Keys → enable **"Report modifiers using CSI u"**
- Or use the fallback: `Alt+Enter` or `Ctrl+J` — these always work

## Image paste doesn't attach

A pasted/dropped path is left as text instead of becoming a chip. Checks:

- The file extension must be one of `.png .jpg .jpeg .gif .bmp .webp .svg .tiff .ico`
- The file must exist at the resolved path
- The path must be absolute. Relative paths aren't extracted

When dragging from Finder/Files, your terminal needs to paste the path; if it doesn't, paste the path manually.

## Thread doesn't appear in `/resume`

`/resume` reads from `~/.deepagent-tui/threads.db` — the local index. A thread is missing when:

- It was created on a different machine
- The local index was deleted
- The thread was created via the LangGraph server directly (not via this TUI)

`/resume <thread_id>` falls back to a server lookup, so you can still attach to threads that aren't in the local index — they'll be added on the next assistant turn.

## `/fork` fails with "no assigned graph ID"

Forking copies state from the source thread, and the server needs a `graph_id` on that thread to do it. A brand-new thread that hasn't completed a run yet doesn't have one. Send at least one message before forking.

## `/compact` reports `Error executing compact_conversation tool.`

The agent doesn't have `SummarizationToolMiddleware` registered, so the `compact_conversation` tool isn't in its tool list. Add the middleware to the server's `create_deep_agent(middleware=[...])` list and restart `langgraph dev`. The recipe is in [server-middleware.md](server-middleware.md#conversation-compaction).

## `/compact` always says `Nothing to compact yet …`

The middleware is registered but the eligibility gate is denying. By design, the gate refuses to compact until reported usage reaches ~50% of the auto-summarization trigger (default: ~42.5% of `max_input_tokens`). For short conversations this is the correct outcome — the tool will fire once the context grows past that threshold.

## `/skills` shows nothing

Two causes:

1. The agent uses `SkillsMiddleware` and hasn't loaded skills yet — send a message, then run `/skills refresh`.
2. The agent doesn't expose skills via metadata or thread state. The TUI can't surface what isn't there.

## `/copy` or `/export` fails on Linux

Both commands share the same clipboard path. The TUI tries `wl-copy` (Wayland), `xsel`, then `xclip` in that order. Install one of them:

```bash
# Wayland
sudo apt install wl-clipboard
# X11
sudo apt install xsel       # or xclip
```

## Theme reverts on restart

`~/.deepagent-tui/theme` couldn't be written (permissions, full disk). The error is silent — check the file exists and is writable. Until then, set `DEEPAGENT_THEME=<name>` to pin the theme via env.

## Approval prompt is stuck

The approval widget polls thread state and loops until no pending interrupts remain. If a reject loops back to another approval prompt, that's expected — the agent often reacts to a rejection by trying a different tool call. Keep rejecting or approve once to break the loop.

If the prompt genuinely hangs (no streaming, no new prompt), `Esc` rejects the current one; `Ctrl+C` quits the TUI. Then check the LangGraph server logs — the run may have errored server-side.

## Status bar shows `$0.0000` for cost

The model name isn't in `MODEL_PRICING` (see `src/deepagent_tui/utils/cost.py`). Add an entry for your model, or accept that cost tracking is best-effort for unknown models.

## Debug mode

Set `DEEPAGENT_DEBUG=1` before launching to surface stream events, tracebacks, and worker errors inline in the transcript:

```bash
DEEPAGENT_DEBUG=1 uv run deepagent-tui
```
