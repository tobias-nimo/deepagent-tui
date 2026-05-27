"""Smoke tests for the Textual TUI.

These boot the App with stubbed connect/discover_skills (so no server
is needed) and assert that the main widgets mount and the most basic
interactions don't blow up. They act as a regression net for the
package rename and the REPL deletion that follow.
"""
from __future__ import annotations

import pytest
from textual.containers import Container, VerticalScroll
from textual.widgets import OptionList

from deepagent_tui import bootstrap as bootstrap_module
from deepagent_tui.tui.app import (
    ChatBar,
    ChatTextArea,
    DeepAgentTUI,
    StatusBar,
    WelcomeBanner,
)


async def _fake_connect(client, session) -> bool:
    session.assistant_id = "test-assistant"
    session.graph_id = "test-graph"
    session.thread_id = "test-thread"
    return True


async def _fake_discover(client, session) -> None:
    return None


@pytest.fixture(autouse=True)
def _stub_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the network-touching bootstrap helpers the TUI calls in on_mount."""
    monkeypatch.setattr(bootstrap_module, "connect", _fake_connect)
    monkeypatch.setattr(bootstrap_module, "discover_and_register_skills", _fake_discover)


async def test_app_boots_and_mounts_core_widgets() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(WelcomeBanner)
        app.query_one(ChatBar)
        app.query_one(ChatTextArea)
        app.query_one(StatusBar)
        app.query_one("#messages", Container)
        app.query_one("#main", VerticalScroll)
        app.query_one("#autocomplete", OptionList)


async def test_autocomplete_hidden_initially() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        ac = app.query_one("#autocomplete", OptionList)
        assert "-hidden" in ac.classes


async def test_slash_prefix_reveals_autocomplete() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Drive the autocomplete logic directly — the TextArea.Changed
        # event takes an extra event-loop tick to land and pilot.pause()
        # has been flaky for that across textual versions.
        app._refresh_autocomplete("/")
        ac = app.query_one("#autocomplete", OptionList)
        assert "-hidden" not in ac.classes
        assert ac.option_count > 0


async def test_status_bar_refresh_uses_session_state() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.input_tokens = 12
        app.session.output_tokens = 34
        sb = app.query_one(StatusBar)
        sb._refresh()  # would raise if any rendering helper broke
        assert "12" in str(sb.content)


async def test_connect_failure_does_not_crash_app(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _failing_connect(client, session) -> bool:
        return False

    monkeypatch.setattr(bootstrap_module, "connect", _failing_connect)
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # App should still have its widgets mounted; the failure path just
        # schedules an exit, it doesn't crash the layout.
        app.query_one(ChatBar)
        app.query_one(StatusBar)


async def test_settings_screen_mounts_and_switches_tabs() -> None:
    """SettingsScreen mounts with four tabs and `_next_tab` cycles through
    them. We call the screen method directly because Pilot's key dispatch
    doesn't reliably route through Screen.on_key when no widget is focused
    on the screen — the logic we're verifying is the tab-cycling state
    machine, not Textual's event plumbing."""
    from deepagent_tui.tui.screens import SettingsScreen

    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SettingsScreen(app.session)
        await app.push_screen(screen)
        await pilot.pause()

        assert screen._active_tab == 0
        assert screen.TABS == ("Config", "Harness", "Usage", "Status")
        screen._next_tab()
        assert screen._active_tab == 1
        screen._next_tab()
        assert screen._active_tab == 2
        screen._next_tab()
        assert screen._active_tab == 3
        screen._next_tab()
        assert screen._active_tab == 0  # wraps
        screen._prev_tab()
        assert screen._active_tab == 3  # wraps backwards


async def test_config_toggle_persists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """`_cycle_current` on the HITL row flips session state and round-trips
    through the on-disk config file. Uses a tmp config dir so the user's
    real config is never touched."""
    from deepagent_tui.storage import config_store
    from deepagent_tui.tui.screens import SettingsScreen

    cfg_dir = tmp_path / ".deepagent-tui"
    monkeypatch.setattr(config_store, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_store, "_CONFIG_FILE", cfg_dir / "config.toml")

    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        initial_hitl = app.session.hitl_enabled
        screen = SettingsScreen(app.session)
        await app.push_screen(screen)
        await pilot.pause()

        # Highlight defaults to row 0 (HITL).
        assert screen._selected_row == 0
        screen._cycle_current(+1)
        assert app.session.hitl_enabled != initial_hitl

        loaded = config_store.load_config()
        assert loaded.hitl_enabled == app.session.hitl_enabled

        # Cycling the Tool widgets row writes the new mode and propagates
        # to the module-level flag used by renderers.
        from deepagent_tui.ui import tool_widgets as tw

        screen._selected_row = 1
        before_mode = app.session.tool_widget_mode
        screen._cycle_current(+1)
        assert app.session.tool_widget_mode != before_mode
        assert tw._WIDGET_MODE == app.session.tool_widget_mode
        assert config_store.load_config().tool_widget_mode == app.session.tool_widget_mode
