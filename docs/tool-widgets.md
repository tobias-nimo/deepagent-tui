# Tool widgets

Built-in tools get custom inline widgets so calls render meaningfully instead of as a JSON blob.

## What gets a widget

> Which tool names are recognized, and what each widget shows (e.g. `edit_file` renders a unified diff; `read_file` shows path + range; etc.).

## Rendering decisions

> How the renderer picks a widget by tool name, what the fallback looks like for unknown tools, when arguments vs. results are shown.

## Adding a widget

> Where widgets live (`src/deepagent_tui/ui/tool_widgets.py`), the contract a widget implements, how to register it so the dispatcher picks it up.

## Implementation pointers

> `ui/tool_widgets.py`, `handlers/tools.py`, `ui/renderer.py`.
