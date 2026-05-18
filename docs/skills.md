# Skills

Skills are reusable agent capabilities exposed by the connected Deep Agent server. The TUI discovers them and surfaces each as a slash command, so `/<skill-name>` is enough to invoke one.

## What a skill is

A skill is a directory containing a `SKILL.md` that the agent reads when invoked — the contract is owned by the agent server, not the TUI. From the TUI's perspective a skill is just a `{name, description, path}` record discovered from the server.

## Discovery

Two discovery paths run, in order:

### 1. Assistant metadata (startup, best-effort)

After `connect()` succeeds, `discover_and_register_skills` queries the assistants list and reads `metadata.skills` (and `metadata.tools`) on the matched assistant. Each entry registers a dynamic slash command. The TUI prints a one-line `Discovered N skill(s) from server metadata. Type /skills to list.` when anything is found.

Most Deep Agents don't expose skills here — they load skills lazily via `SkillsMiddleware`, which writes them into thread state instead.

### 2. Thread state (after the first turn)

After every assistant turn, `_discover_from_thread_state` reads `skills_metadata` from the thread checkpoint (set by `SkillsMiddleware`). New entries are registered as dynamic commands, and `workspace_root` is derived from the first skill path that has at least three parent directories (typically `<workspace>/.deepagent/skills/<name>/SKILL.md` → `<workspace>`).

This is the path most users hit: send a message, the agent loads its skills, the TUI picks them up on the next turn, and they appear in autocomplete.

### `/skills refresh`

Triggers the thread-state path on demand. Useful when:

- You're inspecting an existing thread and don't want to send a message first
- The agent loaded new skills mid-conversation that the TUI didn't pick up

## Invocation

`/<skill-name> [question]` invokes a registered skill. The TUI sends a synthesized user message to the agent:

- With no args: `Use the <name> skill`
- With args: `Use the <name> skill: <question>`

The agent's own routing decides what to do from there (it typically reads the skill's `SKILL.md` and acts). The response streams into the transcript like any other turn.

Skill invocations go through the **same stream worker** as regular messages, not through the dynamic command's registered handler — that handler is a no-op placeholder kept around so the name appears in autocomplete and `/skills`.

## Listing — `/skills`

Opens a full-screen picker (`PickerScreen` in `tui/screens.py`, same widget as `/resume` and `/fork`) listing the currently-registered skills. Type to filter by name or description; ↑↓ to move, Enter to select, Esc to cancel. Selecting a skill fills the chat input with `/<skill-name> ` and focuses it — you can then add arguments and submit, or just press Enter to invoke with no args.

If nothing has been discovered yet, prints a hint suggesting you send a message and then try `/skills refresh`.

## Name collisions

Built-in commands take precedence over dynamic skill commands. If a skill is named `commands`, `help`, `status`, `new`, `clear`, `exit`, `threads`, `resume`, `fork`, `export`, `copy`, `theme`, or `skills`, the built-in wins and the skill is unreachable as a slash command (but still loaded server-side).

## Implementation pointers

- `src/deepagent_tui/bootstrap.py` — `discover_and_register_skills`, `register_skill_command`
- `src/deepagent_tui/client.py` — `discover_skills` (assistant metadata) and `get_skills_from_state` (thread state)
- `src/deepagent_tui/commands/skills.py` — `/skills` and `/skills refresh`
- `src/deepagent_tui/commands/__init__.py` — dynamic registry (`register_skill`, `clear_dynamic`)
- `src/deepagent_tui/tui/app.py:_run_command` — skill invocation routes to `_submit_message`
