"""Voyage AI embeddings — used for run-level similarity and corpora retrieval.

We call the REST API directly (no SDK dependency). VOYAGE_API_KEY env var
required for production use; if missing, the module degrades gracefully
(returns None and the caller skips similarity features).

Model choice: voyage-3-lite ($0.02/Mtok input). Adequate quality for run-level
semantic similarity over BRDs / memos / pitches. Swap to voyage-3-large via
env if you want higher quality at 5x cost.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-3-lite")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

# Voyage charges per 1M tokens. Approximate token estimate: chars / 3.5.
_PRICE_PER_M_TOKENS = {
    "voyage-3-lite": 0.02,
    "voyage-3": 0.06,
    "voyage-3-large": 0.18,
}


class EmbeddingUnavailable(Exception):
    """Raised when VOYAGE_API_KEY isn't configured. Callers should degrade gracefully."""


def is_available() -> bool:
    return bool(VOYAGE_API_KEY)


def _estimate_cost(text_chars: int) -> float:
    rate = _PRICE_PER_M_TOKENS.get(VOYAGE_MODEL, 0.02)
    approx_tokens = text_chars / 3.5
    return (approx_tokens / 1_000_000.0) * rate


async def embed(text: str, *, input_type: str = "document") -> dict:
    """Compute one embedding. Returns {vector, dim, model, approx_cost_usd, tokens}.

    input_type: "document" when storing; "query" when comparing.
    """
    if not VOYAGE_API_KEY:
        raise EmbeddingUnavailable("VOYAGE_API_KEY is not set. Add it to .env to enable similarity.")
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty text.")
    # Voyage caps each input at 32K tokens (~110K chars). Truncate defensively.
    if len(text) > 100_000:
        text = text[:100_000]
    payload = {
        "model": VOYAGE_MODEL,
        "input": [text],
        "input_type": input_type,
    }
    headers = {"Authorization": f"Bearer {VOYAGE_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(VOYAGE_API_URL, headers=headers, content=json.dumps(payload))
        if resp.status_code != 200:
            raise RuntimeError(f"Voyage embed failed ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
    vec = data["data"][0]["embedding"]
    used = (data.get("usage") or {}).get("total_tokens") or 0
    cost = (used / 1_000_000.0) * _PRICE_PER_M_TOKENS.get(VOYAGE_MODEL, 0.02) if used else _estimate_cost(len(text))
    return {
        "vector": vec,
        "dim": len(vec),
        "model": VOYAGE_MODEL,
        "tokens": used,
        "approx_cost_usd": round(cost, 6),
    }


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Voyage embeddings are already L2-normalized so this
    is equivalent to a dot product, but we compute it explicitly for clarity."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))
