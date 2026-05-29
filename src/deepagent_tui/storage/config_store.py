"""User-tunable config persisted to ~/.deepagent-tui/config.toml.

The single home for all persisted preferences: HITL toggle, tool-widget
verbosity, markdown toggle, language, thinking animation, and theme name. A
hand-rolled TOML writer keeps us off `tomli_w` since the file is trivial.
Unknown keys and parse errors fall back to defaults so a stale file from a
future version is never fatal.

Scope: top-level scalar keys are the *defaults* applied to every agent. A
`[graph."<graph_id>"]` table holds per-agent overrides that win over the
defaults when the TUI is connected to that graph. A pre-scoping flat file (no
`[graph.*]` tables) is read unchanged — it simply becomes the default layer,
so the format is backward compatible with no migration step.

`theme` is the empty string when no theme has been explicitly chosen — that
sentinel lets `ui/theme.py` fall back to the `DEEPAGENT_THEME` env var before
the built-in default, preserving the documented precedence order. An empty
theme in a graph table never clobbers a non-empty default.
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
_VALID_THINKING_ANIMATIONS: tuple[str, ...] = (
    "braille",
    "pulse",
    "shimmer",
    "gradient",
    "typewriter",
    "sparkle",
)

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
    thinking_animation: str = "braille"
    theme: str = ""


def _apply(data: dict, cfg: UserConfig) -> None:
    """Overlay recognized keys from `data` onto `cfg` in place. Used for both
    the default layer and a per-graph override layer, so unknown/invalid values
    are skipped (leaving whatever was already on `cfg`)."""
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
    anim = data.get("thinking_animation")
    if isinstance(anim, str) and anim in _VALID_THINKING_ANIMATIONS:
        cfg.thinking_animation = anim
    # Theme is validated against THEMES downstream in ui/theme.py, so accept any
    # non-empty string here and let the loader there reject unknown names. Empty
    # strings are skipped so a graph override never wipes the default theme.
    theme = data.get("theme")
    if isinstance(theme, str) and theme:
        cfg.theme = theme.strip().lower()


def _read_raw() -> dict:
    """Parsed TOML document, or {} on any read/parse failure."""
    try:
        raw = _CONFIG_FILE.read_bytes()
    except (FileNotFoundError, OSError):
        return {}
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def load_config(graph_id: str | None = None) -> UserConfig:
    """Effective config for `graph_id`: the default (top-level) layer with the
    matching `[graph."<graph_id>"]` overrides applied on top. With no graph_id
    (e.g. at startup before connection), only the default layer is returned."""
    data = _read_raw()
    cfg = UserConfig()
    _apply(data, cfg)
    if graph_id:
        graphs = data.get("graph")
        if isinstance(graphs, dict):
            override = graphs.get(graph_id)
            if isinstance(override, dict):
                _apply(override, cfg)
    return cfg


def save_config(cfg: UserConfig, graph_id: str | None = None) -> None:
    """Persist `cfg`. With a graph_id it writes to that graph's override table
    and leaves the defaults and other graphs untouched; without one it rewrites
    the default layer. Existing sections we aren't targeting are preserved."""
    data = _read_raw()
    graphs = data.get("graph")
    graphs = {k: v for k, v in graphs.items() if isinstance(v, dict)} if isinstance(graphs, dict) else {}
    default = {k: v for k, v in data.items() if k != "graph" and not isinstance(v, dict)}

    if graph_id:
        graphs[graph_id] = asdict(cfg)
    else:
        default = asdict(cfg)

    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(_dump_toml(default, graphs))
    except OSError:
        pass


def _dump_toml(default: dict, graphs: dict[str, dict]) -> str:
    """Tiny TOML emitter for our schema: default scalars at the top, then one
    `[graph."<id>"]` table per agent. Not a general-purpose writer."""
    lines: list[str] = [_kv(k, v) for k, v in default.items()]
    for gid, gcfg in graphs.items():
        lines.append("")
        lines.append(f"[graph.{_quote_key(gid)}]")
        lines.extend(_kv(k, v) for k, v in gcfg.items())
    return "\n".join(lines) + "\n"


def _kv(key: str, value: object) -> str:
    if isinstance(value, bool):
        return f"{key} = {'true' if value else 'false'}"
    if isinstance(value, str):
        return f"{key} = {_quote_key(value)}"
    raise TypeError(f"config_store cannot serialize {key!r} of type {type(value).__name__}")


def _quote_key(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
