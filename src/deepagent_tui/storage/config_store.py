"""User-tunable config persisted to ~/.deepagent-tui/config.toml.

Mirrors the single-file pattern used by `ui/theme.py` for the theme name. Two
scalars today (HITL toggle, tool-widget verbosity); a hand-rolled TOML writer
keeps us off `tomli_w` since the file is trivial. Unknown keys and parse
errors fall back to defaults so a stale file from a future version is never
fatal.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

WidgetMode = Literal["compacted", "default", "expanded"]

_CONFIG_DIR = Path.home() / ".deepagent-tui"
_CONFIG_FILE = _CONFIG_DIR / "config.toml"

_VALID_WIDGET_MODES: tuple[WidgetMode, ...] = ("compacted", "default", "expanded")

# Legacy → modern rename. Pre-v2 the toggle was binary ("condensed"/"expanded"),
# where "expanded" meant the current "default" (capped) view. We migrate the
# rename, but intentionally leave legacy "expanded" untouched so the new
# uncapped mode keeps its natural name — flip back to "default" in /settings
# if the old capped behaviour is preferred.
_LEGACY_WIDGET_MODES: dict[str, WidgetMode] = {"condensed": "compacted"}


@dataclass
class UserConfig:
    hitl_enabled: bool = True
    tool_widget_mode: WidgetMode = "default"
    markdown_enabled: bool = True
    language: str = "english"


def load_config() -> UserConfig:
    try:
        raw = _CONFIG_FILE.read_bytes()
    except (FileNotFoundError, OSError):
        return UserConfig()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return UserConfig()

    cfg = UserConfig()
    hitl = data.get("hitl_enabled")
    if isinstance(hitl, bool):
        cfg.hitl_enabled = hitl
    mode = data.get("tool_widget_mode")
    if isinstance(mode, str):
        if mode in _VALID_WIDGET_MODES:
            cfg.tool_widget_mode = mode  # type: ignore[assignment]
        elif mode in _LEGACY_WIDGET_MODES:
            cfg.tool_widget_mode = _LEGACY_WIDGET_MODES[mode]
    md = data.get("markdown_enabled")
    if isinstance(md, bool):
        cfg.markdown_enabled = md
    lang = data.get("language")
    if isinstance(lang, str) and lang:
        cfg.language = lang
    return cfg


def save_config(cfg: UserConfig) -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(_dump_toml(asdict(cfg)))
    except OSError:
        pass


def _dump_toml(data: dict) -> str:
    """Tiny TOML emitter for our flat scalar schema. Booleans render
    lowercase; strings get quoted. Not a general-purpose writer."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            raise TypeError(f"config_store cannot serialize {key!r} of type {type(value).__name__}")
    return "\n".join(lines) + "\n"
