# Testing

The test suite is small on purpose: a single smoke file that catches the kinds of breakage refactors usually introduce.

## What's there today

`tests/test_tui_smoke.py` boots the app with stubbed bootstrap (no server needed) and asserts that the layout mounts and basic interactions don't blow up. Five tests, ~0.5s total.

| Test | What it covers |
|------|----------------|
| `test_app_boots_and_mounts_core_widgets` | The full layout — `WelcomeBanner`, `ChatBar`, `ChatTextArea`, `StatusBar`, `#messages`, `#main`, `#autocomplete` — all mount without error |
| `test_autocomplete_hidden_initially` | `#autocomplete` starts with the `-hidden` class |
| `test_slash_prefix_reveals_autocomplete` | Calling `_refresh_autocomplete("/")` removes `-hidden` and produces options |
| `test_status_bar_refresh_uses_session_state` | Manually mutating `session.input_tokens` / `output_tokens` and calling `StatusBar._refresh()` renders the graph id correctly |
| `test_connect_failure_does_not_crash_app` | When `connect()` returns `False`, the app still mounts its widgets (it schedules an exit instead of crashing) |

## Running

```bash
uv run pytest               # the smoke suite
uv run pytest -k slash      # filter to one test
uv run ruff check           # lint
```

`pytest-asyncio` is configured in `auto` mode (see `pyproject.toml`), so `async def test_...` functions just work.

## The stubbed-bootstrap pattern

The TUI calls `bootstrap.connect` and `bootstrap.discover_and_register_skills` from `on_mount` — both touch the network. An autouse fixture monkeypatches them with fakes that fill `session.assistant_id` / `graph_id` / `thread_id` and return success:

```python
async def _fake_connect(client, session) -> bool:
    session.assistant_id = "test-assistant"
    session.graph_id = "test-graph"
    session.thread_id = "test-thread"
    return True

async def _fake_discover(client, session) -> None:
    return None

@pytest.fixture(autouse=True)
def _stub_bootstrap(monkeypatch):
    monkeypatch.setattr(bootstrap_module, "connect", _fake_connect)
    monkeypatch.setattr(bootstrap_module, "discover_and_register_skills", _fake_discover)
```

This lets every test boot the real `DeepAgentTUI` without standing up a LangGraph server.

## Adding a test

Tests run inside Textual's `pilot` harness:

```python
async def test_my_thing() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # ... interact with app ...
```

`pilot.pause()` yields back to the event loop so mounts and post-mount messages settle. The existing tests sometimes prefer to drive helpers directly (e.g. `app._refresh_autocomplete("/")`) instead of simulating keystrokes — TextArea.Changed has been flaky to await across Textual versions, and direct calls are deterministic.

When asserting on rendered content, query the widget and read its content/attributes (`sb.content`, `ac.option_count`, `"-hidden" in ac.classes`) rather than scraping the screen buffer.

## What's intentionally not tested

- **Live streaming and tool widgets** — would require either a real LangGraph server or a heavy fake of the SDK's async stream protocol. The renderers in `ui/tool_widgets.py` are pure functions of `FormattedToolCall` / `FormattedToolResult`, so they're cheap to unit-test in isolation if a regression appears.
- **HITL approval flow end-to-end** — the widget itself (`InlineApproval`) and the `build_resume_value` builder are unit-testable; gluing them through a fake stream would be brittle. Manual verification covers it.
- **Theme rendering** — visual; eyeballing is the test.
- **Clipboard, terminal image protocols, `$EDITOR` round-trips** — environment-dependent; out of scope for CI.

The smoke tests are the line of defense for "did the wiring still work after a refactor?" — that's the failure mode worth catching automatically.
