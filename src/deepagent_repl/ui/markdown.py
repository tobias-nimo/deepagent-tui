from __future__ import annotations

import re

from rich.markdown import Markdown

from deepagent_repl.ui.theme import markdown_theme


class _ThemedMarkdown:
    """Render a Markdown with the current palette's overrides pushed onto the
    console — so inline code, headings, links, etc. follow the active theme
    instead of Rich's hard-coded cyan/magenta defaults."""

    def __init__(self, md: Markdown) -> None:
        self._md = md

    def __rich_console__(self, console, options):
        console.push_theme(markdown_theme())
        try:
            yield from self._md.__rich_console__(console, options)
        finally:
            console.pop_theme()


def render_markdown(text: str) -> _ThemedMarkdown:
    """Convert a markdown string to a Rich-renderable that respects the
    current UI theme.

    Pre-processes the text to handle edge cases before Rich rendering.
    """
    processed = _preprocess(text)
    return _ThemedMarkdown(Markdown(processed, code_theme="monokai"))


def _preprocess(text: str) -> str:
    """Clean up markdown text before rendering.

    - Normalizes line endings
    - Ensures opening fenced code blocks have a language tag (defaults to 'text')
    """
    text = text.replace("\r\n", "\n")

    # Add 'text' language to opening fences that lack one.
    # Track fence state to only modify opening (not closing) fences.
    lines = text.split("\n")
    result = []
    in_fence = False
    for line in lines:
        if re.match(r"^```\S+", line):
            # Opening fence with language — enter code block
            in_fence = True
            result.append(line)
        elif re.match(r"^```\s*$", line):
            if in_fence:
                # Closing fence
                in_fence = False
                result.append(line)
            else:
                # Opening fence without language — add default
                in_fence = True
                result.append("```text")
        else:
            result.append(line)

    return "\n".join(result)
