# Testing

How the test suite is organized, what it covers, and how to add to it.

## What's there today

> `tests/test_tui_smoke.py` — boots the app with a fake connect/discover and asserts the layout mounts and basic interactions don't blow up. Runs in ~0.5s. First thing to break when wiring is disturbed.

## Running

> `uv run pytest` (smoke) · `uv run ruff check` (lint).

## The stubbed-bootstrap pattern

> How bootstrap is replaced in tests, what the fake client returns, why this lets us exercise the TUI without a live LangGraph server.

## Adding a test

> Where to put it, what helpers are available, common pitfalls (async timing, Textual pilot quirks).

## What's intentionally not tested

> Areas where end-to-end coverage would be brittle and we rely on manual verification instead.
