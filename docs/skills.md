# Skills

Skills are reusable agent capabilities discovered from the connected Deep Agent server and surfaced in the TUI as slash commands.

## What a skill is

> The `SKILL.md` contract — what the agent reads, how it decides to act, why the TUI exposes them as commands.

## Discovery

> When discovery runs, where the list comes from (thread state vs. server metadata), what `/skills refresh` does.

## Invocation

> `/<skill-name> [question]` — argument handling, how the prompt is constructed, where the result is rendered.

## Listing — `/skills`

> What the listing shows, how to read the columns.

## Implementation pointers

> `commands/skills.py`, plus any state-shape assumptions the TUI makes about the server.
