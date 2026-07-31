"""Token counting using tiktoken for both input and output."""

import json
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Default fallback encoding
_DEFAULT_ENCODING = "cl100k_base"

# Model → encoding mapping
_MODEL_ENCODING_MAP = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "o1": "o200k_base",
    "o1-mini": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
}


@lru_cache(maxsize=8)
def _get_encoder(encoding_name: str):
    """Cache tiktoken encoders — they're expensive to create."""
    try:
        import tiktoken
        return tiktoken.get_encoding(encoding_name)
    except Exception as e:
        logger.warning(f"Could not load tiktoken encoder '{encoding_name}': {e}")
        return None


def _resolve_encoding(model: str) -> str:
    """Map a model name to its tiktoken encoding."""
    model_lower = model.lower()
    for pattern, encoding in _MODEL_ENCODING_MAP.items():
        if model_lower.startswith(pattern):
            return encoding
    return _DEFAULT_ENCODING


def count_messages_tokens(messages: list[dict], model: str) -> int:
    """
    Count tokens in a list of OpenAI chat messages.
    Uses the same algorithm as OpenAI's cookbook.
    """
    encoding_name = _resolve_encoding(model)
    encoder = _get_encoder(encoding_name)
    if encoder is None:
        # Fallback: rough estimate (4 chars ≈ 1 token)
        total_chars = sum(len(str(m)) for m in messages)
        return total_chars // 4

    # OpenAI's token counting formula for chat messages
    tokens_per_message = 3  # every message has <|start|>{role}\n{content}<|end|>
    tokens_per_name = 1

    total = 0
    for message in messages:
        total += tokens_per_message
        for key, value in message.items():
            if isinstance(value, str):
                total += len(encoder.encode(value))
            elif isinstance(value, list):
                # Handle content arrays (vision, tool calls)
                for item in value:
                    if isinstance(item, dict) and "text" in item:
                        total += len(encoder.encode(item["text"]))
            if key == "name":
                total += tokens_per_name

    total += 3  # Reply is primed with <|start|>assistant<|message|>
    return total


def count_text_tokens(text: str, model: str) -> int:
    """Count tokens in a plain text string."""
    encoding_name = _resolve_encoding(model)
    encoder = _get_encoder(encoding_name)
    if encoder is None:
        return len(text) // 4
    return len(encoder.encode(text))


def parse_sse_chunk_tokens(chunk_data: str, model: str) -> int:
    """
    Parse an SSE chunk from OpenAI streaming and count output tokens.
    Returns token count extracted from usage field OR estimates from content.
    """
    try:
        if chunk_data.startswith("data: "):
            chunk_data = chunk_data[6:]
        if chunk_data.strip() in ("", "[DONE]"):
            return 0

        data = json.loads(chunk_data)

        # If the final chunk has usage info, use it directly
        if "usage" in data and data["usage"]:
            return data["usage"].get("completion_tokens", 0)

        # Otherwise count content delta characters as a rough estimate
        content = ""
        for choice in data.get("choices", []):
            delta = choice.get("delta", {})
            content += delta.get("content", "") or ""

        if content:
            return count_text_tokens(content, model)

    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return 0


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str,
    pricing_data: list[dict],
) -> float:
    """
    Estimate cost in USD based on token counts and model pricing.

    Args:
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
        model: Model name string
        pricing_data: List of pricing dicts from DB [{model_pattern, input_cost_per_1m, output_cost_per_1m}]

    Returns:
        Estimated cost in USD
    """
    model_lower = model.lower()

    # Find the best matching pricing entry
    matched = None
    best_match_len = 0

    for entry in pricing_data:
        pattern = entry.get("model_pattern", "").lower()
        if model_lower.startswith(pattern) and len(pattern) > best_match_len:
            matched = entry
            best_match_len = len(pattern)

    if matched is None:
        return 0.0

    input_cost = (input_tokens / 1_000_000) * matched["input_cost_per_1m"]
    output_cost = (output_tokens / 1_000_000) * matched["output_cost_per_1m"]
    return round(input_cost + output_cost, 8)
