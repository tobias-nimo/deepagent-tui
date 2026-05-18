# Themes

Nine built-in themes, switchable at runtime and persisted across sessions.

## Catalog

Each theme defines four colors:

- **gradient_start / gradient_end** — RGB endpoints for the ASCII-art banner gradient
- **accent** — used for highlights, the streaming spinner, picker selections, markdown inline code, etc.
- **command** — used for the slash-prefix in submitted messages and the autocomplete entries

| Theme | Accent | Command | Gradient |
|-------|--------|---------|----------|
| `default` | cyan | `#5b7ca8` | cyan → magenta |
| `aesthetic` | `#d6b3ff` | `#ff9ec7` | pink → lavender |
| `vintage` | `#d4a574` | `#c19a6b` | tan → sepia |
| `monochrome` | `#e5e5e5` | `#888888` | light grey → mid grey |
| `terminal` | `#33ff66` | `#00aa44` | bright green → dark green |
| `sunset` | `#ff8c42` | `#ff6b9d` | orange → pink → violet |
| `ocean` | `#5eead4` | `#38bdf8` | teal → indigo |
| `neon` | `#ff2bd6` | `#fff200` | magenta → violet |
| `langchain` | `#a5c8ff` | `#5b9eff` | icy blue → LangChain blue |

Run `/theme` to see the actual swatches in your terminal.

## Switching themes

```text
/theme               # list themes with swatches; mark the current one
/theme ocean         # switch to "ocean" and persist the choice
```

Switching applies immediately to the welcome banner, message rendering, autocomplete, picker, and inline approval.

## Persistence

The chosen theme is written to `~/.deepagent-tui/theme` and reloaded on startup. The persisted file **overrides** the `DEEPAGENT_THEME` env var — once you've used `/theme`, your choice is sticky.

The order of precedence on startup:

1. `~/.deepagent-tui/theme` (if present and valid)
2. `DEEPAGENT_THEME` env var (if set and valid)
3. `default`

## Markdown coloring

Rich's default markdown styles hard-code cyan/magenta for headings, inline code, links, lists, tables, etc. The TUI overrides them via `markdown_theme()` in `ui/theme.py` so markdown rendering follows the active palette. Without that override, switching to e.g. `vintage` would still show cyan inline code, which clashes with the warm tones.

## Adding a theme

Themes are defined in the `THEMES` dict in `src/deepagent_tui/ui/theme.py`. To add one:

1. Add an entry:
   ```python
   "lavender": Theme("lavender", "#b794f4", "#9f7aea", (183, 148, 244), (159, 122, 234)),
   ```
2. Update the `DEEPAGENT_THEME` listing in [configuration.md](configuration.md) and the catalog table above.

The new theme appears in `/theme` automatically — autocomplete and persistence work without further changes.
