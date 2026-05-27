"""Verify SettingsScreen leaves the underlying screen visible above the panel."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from deepagent_tui.session import Session
from deepagent_tui.tui.screens import SettingsScreen


class _Stub(App):
    # Reproduce the production cascade: a bare `Screen` rule plus the
    # SettingsScreen override that the real App CSS adds.
    CSS = """
    Screen { background: $background; }
    SettingsScreen { background: $surface 70%; }
    #chat-top { dock: top; height: 5; background: red; color: white;
                content-align: center middle; }
    #chat-mid { background: blue; color: white; content-align: center middle; height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("CHATBANNER", id="chat-top")
        yield Static("MIDDLE", id="chat-mid")


@pytest.mark.asyncio
async def test_chat_visible_above_panel():
    app = _Stub()
    async with app.run_test(size=(40, 30)) as pilot:
        session = Session()
        session.hitl_enabled = True
        session.tool_widget_mode = "default"
        await app.push_screen(SettingsScreen(session))
        await pilot.pause()

        # Top 9 lines (~30%) should contain the underlying screen content.
        strips = app.screen._compositor.render_strips(app.size)
        top = "\n".join("".join(s.text for s in strip) for strip in strips[:9])
        assert "CHATBANNER" in top, f"chat banner not visible above panel:\n{top}"
