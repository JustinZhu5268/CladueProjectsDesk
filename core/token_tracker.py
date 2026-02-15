"""Token usage tracking and cost calculation."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config import MODELS, CACHE_WRITE_MULTIPLIER, CACHE_READ_MULTIPLIER

log = logging.getLogger(__name__)


@dataclass
class UsageInfo:
    """Token usage from a single API response."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
        }


class TokenTracker:
    """Calculates costs from API usage data."""

    def calculate_cost(self, model_id: str, usage: UsageInfo) -> float:
        """Calculate cost in USD for a single API call."""
        model = MODELS.get(model_id)
        if not model:
            log.warning("Unknown model '%s', using Sonnet 4.5 pricing", model_id)
            model = MODELS["claude-sonnet-4-5-20250929"]

        inp_price = model.input_price / 1_000_000
        out_price = model.output_price / 1_000_000

        cost = (
            usage.input_tokens * inp_price
            + usage.output_tokens * out_price
            + usage.cache_creation_tokens * inp_price * CACHE_WRITE_MULTIPLIER
            + usage.cache_read_tokens * inp_price * CACHE_READ_MULTIPLIER
        )

        log.debug(
            "Cost calc [%s]: %d in + %d out + %d cache_write + %d cache_read = $%.6f",
            model_id, usage.input_tokens, usage.output_tokens,
            usage.cache_creation_tokens, usage.cache_read_tokens, cost,
        )
        return round(cost, 6)

    def estimate_input_cost(self, model_id: str, token_count: int) -> float:
        """Estimate cost for input tokens (pre-send estimate)."""
        model = MODELS.get(model_id)
        if not model:
            model = MODELS["claude-sonnet-4-5-20250929"]
        return round(token_count * model.input_price / 1_000_000, 6)

    def format_cost(self, cost_usd: float) -> str:
        """Format cost for display."""
        if cost_usd < 0.001:
            return f"${cost_usd:.4f}"
        elif cost_usd < 0.10:
            return f"${cost_usd:.3f}"
        else:
            return f"${cost_usd:.2f}"

    def cost_color(self, cost_usd: float) -> str:
        """Return CSS color based on cost threshold."""
        if cost_usd < 0.01:
            return "#27AE60"  # green
        elif cost_usd <= 0.10:
            return "#F39C12"  # yellow/orange
        else:
            return "#E74C3C"  # red

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return len(text) // 4
