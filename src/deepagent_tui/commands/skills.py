"""The /skills command — pick a discovered skill from a searchable list."""

from __future__ import annotations

from deepagent_tui.commands import command, dynamic_commands
from deepagent_tui.tui.screens import PickerItem
from deepagent_tui.ui.renderer import render_info


@command("skills", "Browse available skills from the connected agent")
async def cmd_skills(client, session, args: str) -> None:
    # /skills refresh — re-fetch skills_metadata from thread state
    if args.strip().lower() == "refresh":
        render_info("Fetching skills from thread state...")
        try:
            skills_from_state = await client.get_skills_from_state(session.thread_id)
            if skills_from_state:
                from deepagent_tui.bootstrap import register_skill_command

                session.discovered_skills_from_state = True
                for skill in skills_from_state:
                    name = skill.get("name", "")
                    desc = skill.get("description", "")
                    path = skill.get("path", "")
                    if name:
                        session.discovered_tools[name] = desc
                        register_skill_command(name, desc, path)
                render_info(f"Found {len(skills_from_state)} skill(s). Use /<skill-name> to invoke.")
            else:
                render_info(
                    "No skills_metadata in thread state. "
                    "Send a message first so the agent loads its skills."
                )
        except Exception as e:
            render_info(f"Could not fetch skills: {e}")
        return

    skills = dict(dynamic_commands())
    if not skills:
        render_info("No skills discovered yet. Send a message first to refresh agent state.")
        return

    picker = session.picker
    items = [
        PickerItem(title=f"/{name}", subtitle=desc or "—", value=name)
        for name, desc in sorted(skills.items())
    ]
    chosen = await picker(
        items,
        "Loaded skills",
        subtitle="Pre-fill the chat bar with the selected skill…",
        search_placeholder="Search skills...",
    )
    if chosen is None:
        render_info("Cancelled.")
        return

    render_info(f"/{chosen}")
    fill = session.set_input
    if fill is not None:
        fill(f"/{chosen} ")
