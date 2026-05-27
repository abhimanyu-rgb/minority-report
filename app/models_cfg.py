"""Model routing + pricing config.

One source of truth for: which model serves which role, and how to convert a
usage record into a USD cost. Pricing follows Anthropic's published list prices
(USD per 1M tokens). Update PRICING when those change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Anthropic published list prices (USD per 1,000,000 tokens).
# Source: anthropic.com/pricing. Update here when published prices change.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
}

# Stage -> model. Override per-stage via env if needed for experimentation.
# Max model is Opus 4.6 (Opus 4.7 is too expensive for default use). Brainstorm
# gets the heaviest reasoning model; critique/evolution/VC eval use Sonnet for
# balanced cost/quality; matching is pure JSON pattern-match (Haiku).
MODELS: dict[str, str] = {
    "brainstorm": os.getenv("BRAINSTORM_MODEL", "claude-opus-4-6"),
    "premortem":  os.getenv("PREMORTEM_MODEL",  "claude-sonnet-4-6"),
    "evolution":  os.getenv("EVOLUTION_MODEL",  "claude-sonnet-4-6"),
    "vc_match":   os.getenv("VC_MATCH_MODEL",   "claude-haiku-4-5"),
    "vc_eval":    os.getenv("VC_EVAL_MODEL",    "claude-sonnet-4-6"),
    "vc_consensus": os.getenv("VC_CONSENSUS_MODEL", "claude-sonnet-4-6"),
}


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        rates = PRICING.get(self.model)
        if not rates:
            return 0.0
        c = 0.0
        c += (self.input_tokens / 1_000_000.0) * rates["input"]
        c += (self.output_tokens / 1_000_000.0) * rates["output"]
        c += (self.cache_creation_input_tokens / 1_000_000.0) * rates.get("cache_write", rates["input"])
        c += (self.cache_read_input_tokens / 1_000_000.0) * rates.get("cache_read", rates["input"])
        return c

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def usage_from_response(model: str, response) -> Usage:
    """Extract token usage from an Anthropic SDK response object."""
    u = getattr(response, "usage", None)
    if u is None:
        return Usage(model=model)
    return Usage(
        model=model,
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
    )
