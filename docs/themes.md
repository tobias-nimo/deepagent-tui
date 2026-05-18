# Themes

The TUI ships with eight themes, switchable at runtime and persisted across sessions.

## Catalog

> One section per theme with a screenshot or color swatches.

- `default`
- `aesthetic`
- `vintage`
- `monochrome`
- `terminal`
- `sunset`
- `ocean`
- `neon`

## Switching themes

> `/theme` with no argument lists themes with previews; `/theme <name>` applies one. Persistence in `~/.deepagent-tui/theme`. Env override via `DEEPAGENT_THEME`.

## Adding a theme

> Where themes are defined (`src/deepagent_tui/ui/theme.py`), the palette contract, how to register a new one so it shows up in `/theme` and autocomplete.

## Implementation pointers

> `ui/theme.py`, `commands/theme.py`.
