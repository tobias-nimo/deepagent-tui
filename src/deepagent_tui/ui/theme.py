from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.color import Color, ColorParseError
from rich.theme import Theme as RichTheme

from deepagent_tui.config import settings
from deepagent_tui.storage.config_store import load_config, save_config


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
    "langchain":  Theme("langchain",  "#a5c8ff",  "#5b9eff", (200, 220, 255),  (60, 130, 220)),
}

_CONFIG_DIR = Path.home() / ".deepagent-tui"
# Pre-config.toml the theme name lived in its own bare file. We still read it
# once to migrate the value into config.toml, then delete it.
_LEGACY_THEME_FILE = _CONFIG_DIR / "theme"


def _valid_color(name: str) -> bool:
    try:
        Color.parse(name)
        return True
    except ColorParseError:
        return False


def _read_legacy_theme_file() -> str | None:
    try:
        name = _LEGACY_THEME_FILE.read_text().strip().lower()
    except (FileNotFoundError, OSError):
        return None
    return name if name in THEMES else None


def _load_persisted_name() -> str | None:
    name = load_config().theme.strip().lower()
    if name in THEMES:
        return name
    # Fold a pre-config.toml ~/.deepagent-tui/theme file into config.toml, then
    # remove it so the migration runs exactly once.
    legacy = _read_legacy_theme_file()
    if legacy:
        persist_theme(legacy)
        try:
            _LEGACY_THEME_FILE.unlink()
        except OSError:
            pass
        return legacy
    return None


def _initial_theme() -> Theme:
    persisted = _load_persisted_name()
    if persisted:
        return THEMES[persisted]
    env_name = (getattr(settings, "deepagent_theme", None) or "").strip().lower()
    if env_name and env_name in THEMES:
        return THEMES[env_name]
    return THEMES["default"]


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
    cfg = load_config()
    cfg.theme = name.strip().lower()
    save_config(cfg)


# Resolved once at import. Defined after the helpers above so the legacy-file
# migration in _load_persisted_name can call persist_theme during startup.
_CURRENT: Theme = _initial_theme()

# Back-compat: many callers read _theme.ACCENT_COLOR directly. Keep it in sync
# with the current theme so existing module-attribute access still works.
ACCENT_COLOR: str = _CURRENT.accent


def markdown_theme() -> RichTheme:
    """Rich Theme overriding markdown element styles to match the current
    palette. Rich's defaults hard-code cyan/magenta for inline code, headings,
    links, etc., which leaks the wrong color when a non-cyan theme is active."""
    t = _CURRENT
    accent = t.accent
    command = t.command
    return RichTheme(
        {
            "markdown.code": command,
            "markdown.code_block": accent,
            "markdown.link": f"underline {command}",
            "markdown.link_url": f"underline {command}",
            "markdown.list": "",
            "markdown.item.number": "",
            "markdown.block_quote": "dim",
            "markdown.h1": f"bold underline {accent}",
            "markdown.h2": f"bold underline {accent}",
            "markdown.h3": f"bold {accent}",
            "markdown.h4": f"italic {accent}",
            "markdown.h5": "italic",
            "markdown.h6": "dim italic",
            "markdown.strong": f"dim bold {accent}",
            "markdown.table.border": accent,
            "markdown.table.header": "not bold",
        }
    )
