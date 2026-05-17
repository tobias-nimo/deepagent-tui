# deepagent-tui

A rich terminal REPL for any [LangChain Deep Agent](https://github.com/langchain-ai/deepagents) server. Connect to any LangGraph server, stream responses with live markdown rendering, handle human-in-the-loop interrupts, manage threads, invoke skills, and more.

## Features

- Streaming & Rendering
- Human-in-the-Loop (HITL)
- Skills
- Image support
- Thread Management
- Token & Cost Tracking

## Quick Start

```bash
# Install
uv sync

# Start your Deep Agent server (in another terminal)
cd /path/to/your/agent && uv run langgraph dev --no-browser

# Connect
uv run deepagent-tui
```

## Configuration

Set via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGGRAPH_URL` | `http://localhost:2024` | Server URL |
| `GRAPH_ID` | auto-discover | Specific graph/assistant to connect to |
| `LANGSMITH_API_KEY` | — | API key for authenticated connections |
| `THREAD_ID` | — | Resume a specific thread on startup |
| `DEEPAGENT_THEME` | `default` | UI theme: `default`, `aesthetic`, `vintage`, `monochrome`, `terminal`, `sunset`, `ocean`, `neon` |

## Commands

All commands start with `/` and support **tab completion**.

### Session

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/status` | Connection info, token usage, and cost |
| `/new` | Start a fresh conversation thread |
| `/clear` | Clear the terminal screen |
| `/exit` | Exit the REPL |

### Threads

| Command | Description |
|---------|-------------|
| `/threads` | List saved conversation threads |
| `/resume [thread_id]` | Resume a past thread |
| `/fork` | Browse message history and fork from an earlier point |
| `/compress` | Summarize conversation to reduce token usage |
| `/export` | Export conversation as markdown transcript |
| `/copy` | Copy conversation to clipboard |

### Tools & Skills

| Command | Description |
|---------|-------------|
| `/skills` | List discovered skills from the connected agent |
| `/skills refresh` | Re-fetch skills from thread state |
| `/<skill-name> [question]` | Invoke a skill — the agent reads its SKILL.md to address the question |
| `/rules allow <tool>` | Auto-approve a tool (supports wildcards: `edit_*`) |
| `/rules deny <tool>` | Auto-reject a tool |
| `/rules ask <tool>` | Always prompt for a tool |
| `/rules remove <tool>` | Remove a rule |
| `/rules` | Show current approval rules |

### Media & Visualization

| Command | Description |
|---------|-------------|
| `/image <path> [message]` | Send an image to the agent |
| `/graph` | Render agent's execution graph as Mermaid diagram in the browser |
| `/theme [name]` | Switch UI theme; no argument lists all themes with previews |

## Key Bindings

| Key | Action |
|-----|--------|
| **Enter** | Submit message |
| **Shift+Enter** | Insert newline (kitty/xterm terminals) |
| **Alt+Enter** | Insert newline (universal) |
| **Ctrl+L** | Clear screen |
| **Ctrl+D** | Exit |
| **Tab** | Auto-complete commands |

> **Note on Shift+Enter**: Requires a terminal that supports the [kitty keyboard protocol](https://sw.kovidgoyal.net/kitty/keyboard-protocol/) (Kitty, Ghostty, iTerm2 with protocol enabled). Use Alt+Enter or Ctrl+J as universal alternatives.

## One-Shot Mode

Send a single message without entering the REPL:

```bash
# Streaming output (default)
deepagent-tui "What is the capital of France?"

# Plain text, no streaming
deepagent-tui --no-stream "Summarize this file"

# Raw JSON output
deepagent-tui --json "List all tools"

# Piped input
echo "Explain this error" | deepagent-tui
```

## Troubleshooting

### Shift+Enter not working (iTerm2)

If Shift+Enter does nothing in iTerm2, you need to enable the kitty keyboard protocol:

1. Open **iTerm2 → Settings → Profiles → Keys**
2. Enable **"Report modifiers using CSI u"**
3. Restart your terminal session

This allows iTerm2 to send a distinguishable key sequence for Shift+Enter. Without it, Shift+Enter is identical to Enter at the terminal level. Alt+Enter and Ctrl+J always work as alternatives.

## File Locations

| Path | Purpose |
|------|---------|
| `~/.deepagent-tui/history` | Persistent command history |
| `~/.deepagent-tui/threads.db` | Thread index (SQLite) |
| `~/.deepagent-tui/rules.json` | Tool approval rules |
| `.env` | Configuration |
