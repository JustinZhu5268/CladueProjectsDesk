"""Token usage tracking and cost calculation."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config import (
    MODELS, 
    CACHE_WRITE_MULTIPLIER_5M, 
    CACHE_WRITE_MULTIPLIER_1H, 
    CACHE_READ_MULTIPLIER,
    CACHE_TTL_DEFAULT,
)

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

    def __init__(self, cache_ttl: str = CACHE_TTL_DEFAULT):
        """初始化 TokenTracker，可选指定 cache_ttl ('5m' 或 '1h')"""
        self._cache_ttl = cache_ttl
        self._write_multiplier = CACHE_WRITE_MULTIPLIER_1H if cache_ttl == "1h" else CACHE_WRITE_MULTIPLIER_5M

    @property
    def cache_ttl(self) -> str:
        return self._cache_ttl

    @cache_ttl.setter
    def cache_ttl(self, value: str) -> None:
        """设置缓存 TTL 并更新写入乘数"""
        self._cache_ttl = value
        self._write_multiplier = CACHE_WRITE_MULTIPLIER_1H if value == "1h" else CACHE_WRITE_MULTIPLIER_5M

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
            + usage.cache_creation_tokens * inp_price * self._write_multiplier
            + usage.cache_read_tokens * inp_price * CACHE_READ_MULTIPLIER
        )

        log.debug(
            "Cost calc [%s]: %d in + %d out + %d cache_write (%.2fx) + %d cache_read = $%.6f",
            model_id, usage.input_tokens, usage.output_tokens,
            usage.cache_creation_tokens, self._write_multiplier, usage.cache_read_tokens, cost,
        )
        return round(cost, 6)

    def estimate_cost_with_cache(
        self, 
        model_id: str, 
        system_tokens: int,
        message_tokens: int,
        likely_cache_hit: bool = True,
    ) -> dict:
        """
        预估成本，考虑缓存命中/未命中的情况 (PRD v3 修正)
        
        Returns:
            dict: {
                'estimated_input_tokens': ...,
                'estimated_input_cost': ...,
                'cached_tokens': ...,
                'savings_percent': ...,
            }
        """
        model = MODELS.get(model_id)
        if not model:
            model = MODELS["claude-sonnet-4-5-20250929"]

        inp_price = model.input_price / 1_000_000

        if likely_cache_hit:
            # 缓存命中：系统提示按缓存读取价格计算
            cache_read_cost = system_tokens * inp_price * CACHE_READ_MULTIPLIER
            uncached_cost = message_tokens * inp_price
            total_cost = cache_read_cost + uncached_cost
            cached_tokens = system_tokens
            savings_percent = round((1 - (cache_read_cost + uncached_cost) / 
                                   ((system_tokens + message_tokens) * inp_price)) * 100, 1) if (system_tokens + message_tokens) > 0 else 0
        else:
            # 缓存未命中：全部按原价计算
            total_cost = (system_tokens + message_tokens) * inp_price
            cached_tokens = 0
            savings_percent = 0

        return {
            "estimated_input_tokens": system_tokens + message_tokens,
            "estimated_input_cost": round(total_cost, 6),
            "cached_tokens": cached_tokens,
            "savings_percent": savings_percent,
        }

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
