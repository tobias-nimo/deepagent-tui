from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.color import Color, ColorParseError
from rich.theme import Theme as RichTheme

from deepagent_repl.config import settings


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str
    command: str
    gradient_start: tuple[int, int, int]
    gradient_end: tuple[int, int, int]


THEMES: dict[str, Theme] = {
    "default":    Theme("default",    "cyan",     "#5b7ca8", (34, 211, 238),   (217, 70, 239)),
    "aesthetic":  Theme("aesthetic",  "#d6b3ff",  "#ff9ec7", (255, 179, 217),  (179, 196, 255)),
    "vintage":    Theme("vintage",    "#d4a574",  "#c19a6b", (212, 165, 116),  (101, 67, 33)),
    "monochrome": Theme("monochrome", "#e5e5e5",  "#888888", (240, 240, 240),  (110, 110, 110)),
    "terminal":   Theme("terminal",   "#33ff66",  "#00aa44", (51, 255, 102),   (0, 80, 30)),
    "sunset":     Theme("sunset",     "#ff8c42",  "#ff6b9d", (255, 140, 66),   (155, 81, 224)),
    "ocean":      Theme("ocean",      "#5eead4",  "#38bdf8", (94, 234, 212),   (30, 64, 175)),
    "neon":       Theme("neon",       "#ff2bd6",  "#fff200", (255, 43, 214),   (140, 82, 255)),
}

_CONFIG_DIR = Path.home() / ".deepagent-repl"
_THEME_FILE = _CONFIG_DIR / "theme"


def _valid_color(name: str) -> bool:
    try:
        Color.parse(name)
        return True
    except ColorParseError:
        return False


def _load_persisted_name() -> str | None:
    try:
        name = _THEME_FILE.read_text().strip().lower()
    except (FileNotFoundError, OSError):
        return None
    return name if name in THEMES else None


def _initial_theme() -> Theme:
    persisted = _load_persisted_name()
    if persisted:
        return THEMES[persisted]
    env_name = (getattr(settings, "deepagent_theme", None) or "").strip().lower()
    if env_name and env_name in THEMES:
        return THEMES[env_name]
    return THEMES["default"]


_CURRENT: Theme = _initial_theme()

# Back-compat: many callers read _theme.ACCENT_COLOR directly. Keep it in sync
# with the current theme so existing module-attribute access still works.
ACCENT_COLOR: str = _CURRENT.accent


def current_theme() -> Theme:
    return _CURRENT


def available_themes() -> list[str]:
    return list(THEMES.keys())


def set_theme(name: str) -> bool:
    global _CURRENT, ACCENT_COLOR
    key = name.strip().lower()
    if key not in THEMES:
        return False
    _CURRENT = THEMES[key]
    ACCENT_COLOR = _CURRENT.accent
    return True


def persist_theme(name: str) -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _THEME_FILE.write_text(name.strip().lower())
    except OSError:
        pass


_PTK_ANSI: dict[str, str] = {
    "cyan": "ansicyan",
    "blue": "ansiblue",
    "green": "ansigreen",
    "magenta": "ansimagenta",
    "red": "ansired",
    "yellow": "ansiyellow",
    "white": "ansiwhite",
    "bright_cyan": "ansibrightcyan",
    "bright_blue": "ansibrightblue",
    "bright_green": "ansibrightgreen",
    "bright_magenta": "ansibrightmagenta",
    "bright_red": "ansibrightred",
    "bright_yellow": "ansibrightyellow",
    "bright_white": "ansibrightwhite",
}


def accent_ptk() -> str:
    """Return accent color as a prompt_toolkit fg: style string."""
    color = _CURRENT.accent
    if color.startswith("#"):
        return f"fg:{color}"
    ptk = _PTK_ANSI.get(color)
    if ptk:
        return f"fg:{ptk}"
    return f"fg:{color}"


def markdown_theme() -> RichTheme:
    """Rich Theme overriding markdown element styles to match the current
    palette. Rich's defaults hard-code cyan/magenta for inline code, headings,
    links, etc., which leaks the wrong color when a non-cyan theme is active."""
    t = _CURRENT
    accent = t.accent
    command = t.command
    return RichTheme(
        {
            "markdown.code": f"bold {accent}",
            "markdown.code_block": accent,
            "markdown.link": f"underline {command}",
            "markdown.link_url": f"underline {command}",
            "markdown.list": accent,
            "markdown.item.number": accent,
            "markdown.block_quote": f"dim {accent}",
            "markdown.h1": "bold underline",
            "markdown.h2": f"underline {accent}",
            "markdown.h3": f"bold {accent}",
            "markdown.h4": f"italic {accent}",
            "markdown.table.border": accent,
            "markdown.table.header": f"not bold {accent}",
        }
    )
