"""The /skills command — list discovered skills/tools from the connected agent."""

from __future__ import annotations

from rich.table import Table

import deepagent_repl.ui.theme as _theme
from deepagent_repl.commands import command, dynamic_commands
from deepagent_repl.ui.renderer import console, render_info


@command("skills", "List available skills/tools from the connected agent")
async def cmd_skills(client, session, args: str) -> None:
    # /skills refresh — re-fetch skills_metadata from thread state
    if args.strip().lower() == "refresh":
        render_info("Fetching skills from thread state...")
        try:
            skills_from_state = await client.get_skills_from_state(session.thread_id)
            if skills_from_state:
                from deepagent_repl.cli import _register_skill_command

                session.discovered_skills_from_state = True
                for skill in skills_from_state:
                    name = skill.get("name", "")
                    desc = skill.get("description", "")
                    path = skill.get("path", "")
                    if name:
                        session.discovered_tools[name] = desc
                        _register_skill_command(name, desc, path)
                render_info(f"Found {len(skills_from_state)} skill(s). Use /<skill-name> to invoke.")
            else:
                render_info(
                    "No skills_metadata in thread state. "
                    "Send a message first so the agent loads its skills."
                )
        except Exception as e:
            render_info(f"Could not fetch skills: {e}")
        return

    # Show only registered skill commands (not general tools)
    skills = dict(dynamic_commands())

    if not skills:
        render_info("No skills discovered yet.")
        render_info("Send a message first, then use /skills refresh to fetch from agent state.")
        return

    name_width = max((len(name) + 1 for name in skills), default=10)
    table = Table(show_header=False, box=None, expand=False, padding=(0, 2, 0, 0))
    table.add_column("Skill", style=f"bold {_theme.ACCENT_COLOR}", min_width=name_width)
    table.add_column("Description", style="dim", overflow="fold")

    for name, desc in sorted(skills.items()):
        table.add_row(f"/{name}", desc or "—")

    console.print()
    console.print(table)
    console.print()
    render_info(f"{len(skills)} skill(s). Use /<skill-name> [question] to invoke.")
