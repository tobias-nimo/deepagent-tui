"""Token counting — extract usage metadata from streamed messages."""

from __future__ import annotations


def extract_usage(msg: dict) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from a message's usage_metadata.

    Returns (0, 0) if no usage info is present.
    """
    usage = msg.get("usage_metadata") or msg.get("response_metadata", {}).get("usage", {})
    if not usage:
        return 0, 0

    input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0
    return int(input_tokens), int(output_tokens)
