#!/usr/bin/env python3
"""
Initialize a new skill directory with template files.

Usage:
  uv run python src/skills/skill-creator/scripts/init_skill.py <skill-name> --path ./src/skills

Example:
  uv run python src/skills/skill-creator/scripts/init_skill.py web-research --path ./src/skills
"""

import argparse
import re
import sys
from pathlib import Path

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_SKILL_NAME_LENGTH = 64


def validate_skill_name(name: str) -> str | None:
    """Return an error message, or None if valid."""
    if not name:
        return "Skill name is required"
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return f"Skill name exceeds {MAX_SKILL_NAME_LENGTH} characters"
    if not SKILL_NAME_PATTERN.match(name):
        return "Skill name must be lowercase alphanumeric with hyphens only (e.g., web-research)"
    return None


def create_skill_template(skill_name: str) -> str:
    title = " ".join(word.capitalize() for word in skill_name.split("-"))
    return f"""\
---
name: {skill_name}
description: Brief description of what this skill does and when to use it.
---

# {title}

## Description

[Provide a detailed explanation of what this skill does and when it should be used]

## When to Use

- [Scenario 1: When the user asks...]
- [Scenario 2: When you need to...]
- [Scenario 3: When the task involves...]

## How to Use

### Step 1: [First Action]
[Explain what to do first]

### Step 2: [Second Action]
[Explain what to do next]

### Step 3: [Final Action]
[Explain how to complete the task]

## Best Practices

- [Best practice 1]
- [Best practice 2]
- [Best practice 3]

## Supporting Files

This skill directory can include supporting files referenced in the instructions:
- `scripts/` - Python scripts for automation
- `references/` - Additional reference documentation
- `assets/` - Templates, images, or other assets

## Examples

### Example 1: [Scenario Name]

**User Request:** "[Example user request]"

**Approach:**
1. [Step-by-step breakdown]
2. [Using tools and commands]
3. [Expected outcome]
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize a new skill directory with template files."
    )
    parser.add_argument("skill_name", help="Name of the skill (lowercase, hyphens allowed)")
    parser.add_argument("--path", required=True, help="Directory where the skill folder will be created")
    args = parser.parse_args()

    error = validate_skill_name(args.skill_name)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    skill_dir = Path(args.path).expanduser() / args.skill_name

    if skill_dir.exists():
        print(f"Error: Skill directory already exists: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    for subdir in ("scripts", "references", "assets"):
        (skill_dir / subdir).mkdir(parents=True)
        (skill_dir / subdir / ".gitkeep").write_text(f"# Add your {subdir} here\n")

    (skill_dir / "SKILL.md").write_text(create_skill_template(args.skill_name))

    print(f"✓ Skill '{args.skill_name}' created successfully!")
    print(f"  Location: {skill_dir}")
    print(f"\nNext steps:")
    print(f"  1. Edit {skill_dir / 'SKILL.md'} to customize the skill")
    print(f"  2. Add any supporting scripts, references, or assets")


if __name__ == "__main__":
    main()
