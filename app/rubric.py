"""Per-user, persona-gated rubric tuning.

Only the 'investor' persona may tune. Tuning consists of three pillar weights
that sum to 100. They're injected into the premortem prompt so the model
adjusts its scoring emphasis. The composite final score remains the model's
output (we don't re-weight after the fact — the prompt change is the lever).

Storage: app/data/user_rubrics.json — {user_id: {market, feasibility, founder}}.
"""

from __future__ import annotations

import json
from pathlib import Path

RUBRICS_PATH = Path(__file__).resolve().parent / "data" / "user_rubrics.json"

DEFAULT_WEIGHTS = {"market": 34, "feasibility": 33, "founder": 33}

# Only this persona is allowed to tune.
TUNABLE_PERSONAS = {"investor"}


def _load_store() -> dict:
    if not RUBRICS_PATH.is_file():
        return {}
    try:
        return json.loads(RUBRICS_PATH.read_text())
    except Exception:
        return {}


def _save_store(d: dict) -> None:
    RUBRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUBRICS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(RUBRICS_PATH)


def get_weights(user_id: str | None) -> dict:
    """Return the user's rubric weights, or defaults."""
    if not user_id:
        return dict(DEFAULT_WEIGHTS)
    store = _load_store()
    w = store.get(user_id.strip().lower())
    if not w:
        return dict(DEFAULT_WEIGHTS)
    return {k: int(w.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}


def set_weights(user_id: str, persona: str, weights: dict) -> dict:
    """Persist a user's weights. Raises ValueError on bad inputs."""
    if (persona or "").strip().lower() not in TUNABLE_PERSONAS:
        raise ValueError(f"Persona '{persona}' may not tune the rubric. Investor-only.")
    if not user_id or not user_id.strip():
        raise ValueError("user_id required")
    try:
        clean = {k: int(weights.get(k, 0)) for k in DEFAULT_WEIGHTS}
    except (TypeError, ValueError) as e:
        raise ValueError(f"Weights must be integers: {e}")
    for k, v in clean.items():
        if v < 0 or v > 100:
            raise ValueError(f"{k}={v} out of range [0, 100]")
    total = sum(clean.values())
    if not (95 <= total <= 105):
        raise ValueError(f"Weights must sum to ~100; got {total}")
    store = _load_store()
    store[user_id.strip().lower()] = clean
    _save_store(store)
    return clean


def render_weights_block(weights: dict, persona: str) -> str:
    """Return a block to inject into the premortem prompt when weights are tuned.

    Empty string for non-tunable personas or default weights — no need to
    pollute the prompt when nothing has changed.
    """
    if (persona or "").lower() not in TUNABLE_PERSONAS:
        return ""
    if weights == DEFAULT_WEIGHTS:
        return ""
    return (
        "\n## Reviewer rubric weighting\n"
        "This reviewer has explicitly weighted the three pillars as:\n"
        f"- **Market:** {weights['market']}%\n"
        f"- **Feasibility:** {weights['feasibility']}%\n"
        f"- **Founder / team:** {weights['founder']}%\n\n"
        "Tilt your scoring emphasis accordingly. A pillar weighted ≥45% should "
        "dominate the verdict if it's weak; a pillar weighted ≤25% should not "
        "alone gate a green-light.\n"
    )
