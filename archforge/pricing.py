"""DeepSeek pricing and cost calculation.

Source: DeepSeek official pricing page (api-docs.deepseek.com/zh-cn/quick_start/pricing),
checked 2026-10-24. Prices are CNY per 1M tokens at PEAK; off-peak is half.

Peak = Beijing time (UTC+8), Monday-Friday, 09:00-12:00 and 14:00-18:00.
Everything else (evenings, nights, weekends) is off-peak.
Public holidays are also off-peak, but we ignore them on purpose: treating a
holiday as peak can only OVER-estimate cost, which is the safe direction
for a budget guard.

Billing model (why there are three prices):
  - cache hit  : input tokens whose prefix DeepSeek already has cached (very cheap)
  - cache miss : new input tokens
  - output     : generated tokens; in thinking mode this INCLUDES reasoning tokens
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))   # China has no daylight saving, so a fixed offset is exact

# model -> (cache_hit, cache_miss, output) in CNY per 1M tokens, PEAK prices
PEAK_PRICES_CNY = {
    "deepseek-v4-pro": (0.30, 9.0, 27.0),
    "deepseek-flash": (0.04, 2.0, 8.0),
}


def is_peak(when: datetime | None = None) -> bool:
    t = (when or datetime.now(timezone.utc)).astimezone(BEIJING)
    if t.weekday() >= 5:            # Saturday=5, Sunday=6
        return False
    h = t.hour
    return 9 <= h < 12 or 14 <= h < 18


def price_table(model: str, peak: bool) -> tuple[float, float, float]:
    if model not in PEAK_PRICES_CNY:
        raise KeyError(f"No price known for model '{model}'. Add it to PEAK_PRICES_CNY.")
    hit, miss, out = PEAK_PRICES_CNY[model]
    f = 1.0 if peak else 0.5
    return hit * f, miss * f, out * f


@dataclass
class Usage:
    """Normalised token usage of one API call."""
    cache_hit: int = 0
    cache_miss: int = 0
    output: int = 0          # includes reasoning tokens
    reasoning: int = 0       # informational: part of `output`

    @property
    def prompt(self) -> int:
        return self.cache_hit + self.cache_miss

    @property
    def hit_rate(self) -> float:
        return self.cache_hit / self.prompt if self.prompt else 0.0

    @classmethod
    def from_api(cls, u) -> "Usage":
        """Build from the `usage` object DeepSeek returns."""
        def g(obj, name, default=0):
            v = getattr(obj, name, None) if obj is not None else None
            if v is None and isinstance(obj, dict):
                v = obj.get(name)
            return default if v is None else v

        hit = g(u, "prompt_cache_hit_tokens")
        miss = g(u, "prompt_cache_miss_tokens")
        if hit == 0 and miss == 0:           # fallback if the DeepSeek-specific fields are absent
            miss = g(u, "prompt_tokens")
        details = g(u, "completion_tokens_details", None)
        return cls(cache_hit=hit, cache_miss=miss,
                   output=g(u, "completion_tokens"),
                   reasoning=g(details, "reasoning_tokens") if details else 0)


def cost_cny(model: str, usage: Usage, when: datetime | None = None, mode: str = "auto") -> float:
    peak = True if mode == "peak" else is_peak(when)
    hit_p, miss_p, out_p = price_table(model, peak)
    return (usage.cache_hit * hit_p + usage.cache_miss * miss_p + usage.output * out_p) / 1_000_000
