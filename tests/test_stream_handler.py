"""Unit tests for the text-streaming delta logic in handlers/stream.py.

`process_messages_event` must emit only the newly-added tail regardless of
whether the server frames `messages/partial` payloads as cumulative
messages-so-far (type "ai") or as token deltas (type "AIMessageChunk").
`process_updates_event` resets the tail tracker at each message boundary.
"""

from __future__ import annotations

from deepagent_tui.handlers.stream import (
    StreamState,
    process_messages_event,
    process_updates_event,
)


def _partial(text: str, msg_type: str) -> list[dict]:
    return [{"type": msg_type, "content": text}]


def test_cumulative_partials_emit_only_the_tail():
    state = StreamState()
    frags = [
        process_messages_event(_partial("Hello", "ai"), state),
        process_messages_event(_partial("Hello world", "ai"), state),
        process_messages_event(_partial("Hello world!", "ai"), state),
    ]
    assert frags == ["Hello", " world", "!"]
    assert "".join(frags) == state.text_buffer


def test_token_delta_partials_are_appended():
    state = StreamState()
    frags = [
        process_messages_event(_partial("Hello", "AIMessageChunk"), state),
        process_messages_event(_partial(" world", "AIMessageChunk"), state),
        process_messages_event(_partial("!", "AIMessageChunk"), state),
    ]
    assert frags == ["Hello", " world", "!"]
    assert state.text_buffer == "Hello world!"


def test_no_new_text_returns_none():
    state = StreamState()
    process_messages_event(_partial("Hello", "ai"), state)
    # Same cumulative payload again — nothing new to emit.
    assert process_messages_event(_partial("Hello", "ai"), state) is None


def test_updates_boundary_resets_tail_tracker():
    """A second streamed message in the same run starts its cumulative
    partials from scratch; without a reset its first tail would re-include
    the whole message."""
    state = StreamState()
    process_messages_event(_partial("First message.", "ai"), state)

    # Message boundary: parent `updates` event finalizes the first message.
    process_updates_event(
        {"agent": {"messages": [{"type": "ai", "content": "First message."}]}},
        state,
    )
    assert state.text_buffer == ""

    # Second message streams cumulatively from empty again.
    f1 = process_messages_event(_partial("Second", "ai"), state)
    f2 = process_messages_event(_partial("Second message", "ai"), state)
    assert f1 == "Second"
    assert f2 == " message"
