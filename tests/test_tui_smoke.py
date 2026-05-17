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

from deepagent_tui import cli as cli_module
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
    monkeypatch.setattr(cli_module, "connect", _fake_connect)
    monkeypatch.setattr(cli_module, "discover_and_register_skills", _fake_discover)


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
        assert "test-graph" in str(sb.content)


async def test_connect_failure_does_not_crash_app(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _failing_connect(client, session) -> bool:
        return False

    monkeypatch.setattr(cli_module, "connect", _failing_connect)
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # App should still have its widgets mounted; the failure path just
        # schedules an exit, it doesn't crash the layout.
        app.query_one(ChatBar)
        app.query_one(StatusBar)
