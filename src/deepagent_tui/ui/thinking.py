"""Thinking-indicator animations for the streaming slot.

A small registry of named animations, each a function `(frame: int) -> Text`
called at ~10fps while the agent is thinking. The active animation is chosen
in /settings and persisted to config.toml; `set_animation` mirrors the choice
into module state so `render(frame)` picks it up. Color-driven animations read
the live theme accent/gradient, so they follow /theme changes for free.
"""

from __future__ import annotations

import math

from rich.text import Text

import deepagent_tui.ui.theme as _theme

LABEL = "Thinking…"

# Order is the cycle order in /settings (←/→). "braille" is the default.
ANIMATION_KEYS: tuple[str, ...] = (
    "braille",
    "pulse",
    "shimmer",
    "gradient",
    "typewriter",
    "sparkle",
)

_BRAILLE = ["⠋", "⠙", "⠚", "⠞", "⠖", "⠦", "⠴", "⠲", "⠳", "⠓"]
_PULSE = ["·", "•", "●", "⬤", "●", "•"]
_SPARKLE = [".", "✦", "✧", "⋆", "✺", "⋆", "✧", "✦"]

_WORD = "Thinking"
# Type the word one char at a time, grow the ellipsis, then hold before looping.
_TYPEWRITER_STEPS: tuple[str, ...] = tuple(
    [_WORD[:i] for i in range(1, len(_WORD) + 1)]
    + [_WORD + ".", _WORD + "..", _WORD + "..."]
    + [_WORD + "..."] * 4
)


def _glyph(glyph: str) -> Text:
    """`<glyph>  Thinking…` — accent glyph beside a dim fixed label."""
    accent = _theme.ACCENT_COLOR
    return Text.assemble((glyph, f"bold {accent}"), (f"  {LABEL}", "dim"))


def _braille(frame: int) -> Text:
    return _glyph(_BRAILLE[frame % len(_BRAILLE)])


def _pulse(frame: int) -> Text:
    return _glyph(_PULSE[(frame // 2) % len(_PULSE)])


def _sparkle(frame: int) -> Text:
    return _glyph(_SPARKLE[(frame // 2) % len(_SPARKLE)])


def _typewriter(frame: int) -> Text:
    accent = _theme.ACCENT_COLOR
    return Text(_TYPEWRITER_STEPS[(frame // 2) % len(_TYPEWRITER_STEPS)], style=f"bold {accent}")


def _shimmer(frame: int) -> Text:
    """A bright highlight sweeps left→right across a dim label, with a short
    gap before it restarts."""
    accent = _theme.ACCENT_COLOR
    pos = frame % (len(LABEL) + 6)
    out = Text()
    for i, ch in enumerate(LABEL):
        d = abs(pos - i)
        if d == 0:
            out.append(ch, style=f"bold {accent}")
        elif d == 1:
            out.append(ch, style=accent)
        else:
            out.append(ch, style="dim")
    return out


def _gradient(frame: int) -> Text:
    """A sine-driven color wave drifts through the label, interpolating between
    the theme's two gradient stops."""
    t = _theme.current_theme()
    start, end = t.gradient_start, t.gradient_end
    out = Text()
    for i, ch in enumerate(LABEL):
        w = (math.sin(i * 0.6 - frame * 0.25) + 1) / 2
        r = round(start[0] + (end[0] - start[0]) * w)
        g = round(start[1] + (end[1] - start[1]) * w)
        b = round(start[2] + (end[2] - start[2]) * w)
        out.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return out


_ANIMATIONS = {
    "braille": _braille,
    "pulse": _pulse,
    "shimmer": _shimmer,
    "gradient": _gradient,
    "typewriter": _typewriter,
    "sparkle": _sparkle,
}

_current = "braille"


def set_animation(key: str) -> None:
    global _current
    if key in _ANIMATIONS:
        _current = key


def render(frame: int) -> Text:
    return _ANIMATIONS.get(_current, _braille)(frame)
