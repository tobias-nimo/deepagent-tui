"""Smoke tests for the Textual TUI.

These boot the App with stubbed connect/discover_skills (so no server
is needed) and assert that the main widgets mount and the most basic
interactions don't blow up. They act as a regression net for the
package rename and the REPL deletion that follow.
"""
from __future__ import annotations

import pytest
from textual.containers import Container, VerticalScroll
from textual.widgets import OptionList, Static

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
    """`_cycle_current` on the Auto-approve tools row flips session state and
    round-trips through the on-disk config file. Uses a tmp config dir so the
    user's real config is never touched."""
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

        # Highlight defaults to row 0 (Tool widgets).
        assert screen._selected_row == 0

        # Auto-approve tools lives on row 1 — toggling flips hitl_enabled.
        screen._selected_row = 1
        screen._cycle_current(+1)
        assert app.session.hitl_enabled != initial_hitl

        # Settings are scoped to the connected agent, so the toggle round-trips
        # through that graph's override layer — not the shared default.
        loaded = config_store.load_config(app.session.graph_id)
        assert loaded.hitl_enabled == app.session.hitl_enabled

        # Cycling the Tool widgets row (row 0) writes the new mode and
        # propagates to the module-level flag used by renderers.
        from deepagent_tui.ui import tool_widgets as tw

        screen._selected_row = 0
        before_mode = app.session.tool_widget_mode
        screen._cycle_current(+1)
        assert app.session.tool_widget_mode != before_mode
        assert tw._WIDGET_MODE == app.session.tool_widget_mode
        assert (
            config_store.load_config(app.session.graph_id).tool_widget_mode
            == app.session.tool_widget_mode
        )

        # Cycling the Code snippets style row (row 3) writes the new Pygments
        # style, propagates to the markdown module, and round-trips to disk.
        from deepagent_tui.ui import markdown as md

        screen._selected_row = 3
        before_theme = app.session.code_theme
        screen._cycle_current(+1)
        assert app.session.code_theme != before_theme
        assert app.session.code_theme in config_store._VALID_CODE_THEMES
        assert md._code_theme == app.session.code_theme
        assert (
            config_store.load_config(app.session.graph_id).code_theme
            == app.session.code_theme
        )


async def test_at_prefix_reveals_file_list(tmp_path) -> None:
    (tmp_path / "alpha.txt").write_text("x")
    (tmp_path / "beta.txt").write_text("y")
    (tmp_path / "subdir").mkdir()
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = str(tmp_path)
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.text = "look at @a"
        prompt.move_cursor(prompt.document.end)
        app._refresh_autocomplete(prompt.text)
        ac = app.query_one("#autocomplete", OptionList)
        assert "-hidden" not in ac.classes
        assert app._ac_mode == "file"
        ids = {ac.get_option_at_index(i).id for i in range(ac.option_count)}
        assert "alpha.txt" in ids


async def test_at_before_workspace_known_shows_hint() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = None  # no message sent yet
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.text = "see @"
        prompt.move_cursor(prompt.document.end)
        app._refresh_autocomplete(prompt.text)
        ac = app.query_one("#autocomplete", OptionList)
        assert "-hidden" not in ac.classes
        assert ac.option_count == 1
        # The hint row carries no id, so Tab / click does nothing.
        assert ac.get_option_at_index(0).id is None


async def test_shell_before_workspace_known_does_not_run() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = None
        app._run_shell_command("!echo should-not-run", "echo should-not-run")
        msgs = app.query_one("#messages", Container)
        joined = "\n".join(
            str(w.content) for w in msgs.children if isinstance(w, Static)
        )
        assert "Send a message first" in joined


async def test_shell_after_message_hints_at_middleware() -> None:
    # Once a message has been sent but the workspace never loaded, the hint
    # should point at the missing server middleware rather than ask the user
    # to send a message they already sent.
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = None
        app.session.messages = [{"role": "user", "content": "hi"}]
        app._run_shell_command("!echo nope", "echo nope")
        msgs = app.query_one("#messages", Container)
        joined = "\n".join(
            str(w.content) for w in msgs.children if isinstance(w, Static)
        )
        assert "Send a message first" not in joined
        assert "docs/server-middleware.md" in joined


async def test_at_completion_after_message_hints_at_middleware() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = None
        app.session.messages = [{"role": "user", "content": "hi"}]
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.text = "see @"
        prompt.move_cursor(prompt.document.end)
        app._refresh_autocomplete(prompt.text)
        ac = app.query_one("#autocomplete", OptionList)
        assert "-hidden" not in ac.classes
        assert ac.option_count == 1
        label = str(ac.get_option_at_index(0).prompt)
        assert "Send a message first" not in label
        assert "docs/server-middleware.md" in label


async def test_at_completion_replaces_token(tmp_path) -> None:
    (tmp_path / "alpha.txt").write_text("x")
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = str(tmp_path)
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.text = "look at @a"
        prompt.move_cursor(prompt.document.end)
        app._refresh_autocomplete(prompt.text)
        app._apply_file_completion("alpha.txt")
        assert prompt.text == "look at @alpha.txt "
        assert app._ac_mode == "none"


async def test_email_does_not_trigger_file_list(tmp_path) -> None:
    (tmp_path / "alpha.txt").write_text("x")
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = str(tmp_path)
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.text = "mail me@example"
        prompt.move_cursor(prompt.document.end)
        app._refresh_autocomplete(prompt.text)
        ac = app.query_one("#autocomplete", OptionList)
        assert "-hidden" in ac.classes
        assert app._ac_mode == "none"


async def test_render_shell_output_mounts_widget() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._render_shell_output("hello\nworld", 0)
        msgs = app.query_one("#messages", Container)
        joined = "\n".join(
            str(w.content) for w in msgs.children if isinstance(w, Static)
        )
        assert "hello" in joined and "world" in joined


async def test_exec_shell_runs_local_command() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._exec_shell("echo hello-shell-marker")
        msgs = app.query_one("#messages", Container)
        joined = "\n".join(
            str(w.content) for w in msgs.children if isinstance(w, Static)
        )
        assert "hello-shell-marker" in joined


async def test_resolve_file_refs_rewrites_existing(tmp_path) -> None:
    books = tmp_path / "books"
    books.mkdir()
    (books / "blah.md").write_text("hi")
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = str(tmp_path)
        display, agent = app._resolve_file_refs("read @books/blah.md please")
        assert display == "read @blah.md please"
        assert agent == f"read [blah.md]({books / 'blah.md'}) please"


async def test_resolve_file_refs_leaves_unknown(tmp_path) -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.session.workspace_root = str(tmp_path)
        # A casual @-mention that isn't a real file stays verbatim.
        display, agent = app._resolve_file_refs("ping @john now")
        assert display == "ping @john now"
        assert agent == "ping @john now"


async def test_input_history_recall_and_draft_restore() -> None:
    """`up` walks older submissions into the chat bar, `down` walks back, and
    stepping past the newest entry restores the draft stashed on entry. Drive
    the recall methods directly — the key handler is a thin wrapper over them
    and pilot key dispatch is flaky for unfocused-edge cases."""
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", ChatTextArea)
        app._input_history = ["first message", "second message"]
        prompt.text = "draft in progress"

        # up → newest entry (stashing the draft), then the older one.
        assert app._history_recall_prev() is True
        assert prompt.text == "second message"
        assert app._history_recall_prev() is True
        assert prompt.text == "first message"
        # up at the oldest entry is swallowed without moving.
        assert app._history_recall_prev() is True
        assert prompt.text == "first message"

        # down steps back toward newer, then restores the draft and exits.
        assert app._history_recall_next() is True
        assert prompt.text == "second message"
        assert app._history_recall_next() is True
        assert prompt.text == "draft in progress"
        assert app._history_index is None
        # down with no active navigation lets the arrow move the cursor.
        assert app._history_recall_next() is False


async def test_input_history_recall_empty_is_noop() -> None:
    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.text = "typed"
        # No history yet → up does nothing and lets the cursor move.
        assert app._history_recall_prev() is False
        assert prompt.text == "typed"


async def test_plain_paste_inserts_text_once() -> None:
    """Regression: pasting plain text must insert it exactly once. Textual's
    dispatcher walks the MRO and invokes both ChatTextArea._on_paste and the
    base TextArea._on_paste, so the override must not also call super() — doing
    so doubled the pasted text in the chat bar."""
    from textual import events

    app = DeepAgentTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", ChatTextArea)
        prompt.focus()
        await pilot.pause()
        # Mirror how the App delivers a paste: _forward_event marks it forwarded
        # so the bubble back up to the App isn't re-forwarded (a fresh Paste
        # posted directly would loop and double on its own, masking the fix).
        prompt._forward_event(events.Paste(text="hello world"))
        await pilot.pause()
        assert prompt.text == "hello world"


def _colored_text(t, color: str) -> str:
    """Concatenate the characters of `t` that carry `color` in their span."""
    return "".join(
        t.plain[s.start : s.end] for s in t.spans if color in str(s.style)
    )


def test_shell_message_renders_fully_in_command_color() -> None:
    from deepagent_tui.tui.app import _command_color, _user_message_text

    t = _user_message_text("!ls -la /tmp")
    assert "!ls -la /tmp" in _colored_text(t, _command_color())


def test_file_ref_token_renders_in_command_color() -> None:
    from deepagent_tui.tui.app import _command_color, _user_message_text

    t = _user_message_text("look at @src/main.py please")
    colored = _colored_text(t, _command_color())
    assert "@src/main.py" in colored
    assert "please" not in colored
