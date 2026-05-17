from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StreamState:
    """Tracks state while processing a streamed response."""

    text_buffer: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    seen_tool_call_ids: set[str] = field(default_factory=set)
    is_complete: bool = False
    current_role: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model: str | None = None

    def reset(self) -> None:
        self.text_buffer = ""
        self.tool_calls.clear()
        self.tool_results.clear()
        self.seen_tool_call_ids.clear()
        self.is_complete = False
        self.current_role = None


def extract_text_content(content) -> str:
    """Extract text from message content (handles both str and list formats)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def process_messages_event(data: list | dict, state: StreamState) -> str | None:
    """Process a 'messages/partial' or 'messages/complete' stream event.

    The data is a list of message chunk dicts.
    Returns new text fragment if this is an AI text chunk, else None.
    """
    chunks = data if isinstance(data, list) else [data]
    new_text = ""

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        msg_type = chunk.get("type")

        # AIMessageChunk — streaming text token
        if msg_type == "AIMessageChunk":
            content = chunk.get("content", "")
            text = extract_text_content(content)
            if text:
                state.text_buffer += text
                state.current_role = "ai"
                new_text += text

            # Streaming tool call chunks (partial args)
            for tc in chunk.get("tool_call_chunks", []):
                tc_id = tc.get("id")
                if tc_id and tc_id not in state.seen_tool_call_ids:
                    state.seen_tool_call_ids.add(tc_id)
                    state.tool_calls.append({
                        "id": tc_id,
                        "name": tc.get("name", ""),
                        "args": tc.get("args", ""),
                    })

    return new_text if new_text else None


def process_updates_event(data: dict, state: StreamState) -> list[dict]:
    """Process an 'updates' stream event (node-level update).

    Returns list of messages found in the update for tool call/result rendering.
    """
    messages = []
    if not isinstance(data, dict):
        return messages

    for _node_name, node_output in data.items():
        if not isinstance(node_output, dict):
            continue
        node_msgs = node_output.get("messages", [])
        if not isinstance(node_msgs, list):
            continue

        for msg in node_msgs:
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")

            if msg_type == "ai":
                # Collect full tool calls from updates (more reliable than chunks)
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if tc_id not in state.seen_tool_call_ids:
                        state.seen_tool_call_ids.add(tc_id)
                        state.tool_calls.append(tc)

                # Extract usage metadata
                from deepagent_tui.utils.tokens import extract_usage

                inp, out = extract_usage(msg)
                state.total_input_tokens += inp
                state.total_output_tokens += out

                # Extract model name
                resp_meta = msg.get("response_metadata", {})
                model_name = resp_meta.get("model_name") or resp_meta.get("model")
                if model_name:
                    state.model = model_name

                messages.append(msg)

            elif msg_type == "tool":
                state.tool_results.append(msg)
                messages.append(msg)

    return messages
