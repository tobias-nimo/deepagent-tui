"""Cost calculation based on model-specific token pricing."""

from __future__ import annotations

# Pricing per 1M tokens (input, output) in USD
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Claude 4.5 / 4.6 family
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # GPT 5 family
    "gpt-5.4-2026-03-05": (2.5, 15.0),
    "gpt-5.4-mini-2026-03-17": (0.75, 4.5),
    "gpt-5.4-nano-2026-03-17": (0.2, 1.25),
    # GPT OSS family
    "openai/gpt-oss-120b": (0.075, 0.30),
    "openai/gpt-oss-20b":  (0.15, 0.60),
}

# Default pricing if model is unknown
DEFAULT_PRICING = (0.0, 0.0)


def compute_cost(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    """Compute cost in USD for a given token count and model."""
    pricing = DEFAULT_PRICING
    if model:
        # Try exact match first, then prefix match
        if model in MODEL_PRICING:
            pricing = MODEL_PRICING[model]
        else:
            for key, val in MODEL_PRICING.items():
                if model.startswith(key) or key.startswith(model):
                    pricing = val
                    break

    input_rate, output_rate = pricing
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def format_cost(cost: float) -> str:
    """Format a cost value for display."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def format_tokens(count: int) -> str:
    """Format a token count for compact display."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)
