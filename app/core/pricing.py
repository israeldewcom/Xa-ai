"""Model pricing table (micros per 1K tokens). Add entries as you onboard
models. The 'default' entry is intentionally expensive so unknown models don't
look free."""
from app.config import get_settings

_s = get_settings()

# micros per 1K tokens
PRICE_TABLE: dict[str, dict[str, int]] = {
    "qwen2.5-1.5b-instruct": {"input": 10, "output": 30},
    "qwen2.5-7b-instruct": {"input": 50, "output": 150},
    "qwen2.5-72b-instruct": {"input": 400, "output": 1200},
    "default": {"input": 100, "output": 300},
}


def cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    """Total cost in micros ($0.000001)."""
    prices = PRICE_TABLE.get(model) or PRICE_TABLE["default"]
    raw = input_tokens * prices["input"] + output_tokens * prices["output"]
    # Round up so any non-zero usage is never reported as free.
    return -(-raw // 1000)
