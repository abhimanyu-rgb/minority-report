"""Persona definitions and baselines for the user-facing analytics.

Each persona has a baseline_minutes — an estimate of how long this kind of
report would take to produce manually. Used to compute the 'time saved' KPI
in the user analytics tab.

These are starting estimates. Tune them based on real customer conversations.
"""

from __future__ import annotations

PERSONAS = {
    "investor": {
        "label": "Investor (VC / PE)",
        "baseline_minutes": 180,  # 3 hrs: screening a deck, drafting an IC note
        "description": "VC / PE screening a deck or drafting a quick investment memo.",
    },
    "founder": {
        "label": "Founder",
        "baseline_minutes": 360,  # 6 hrs: drafting and iterating a BRD solo
        "description": "Founder drafting / sharpening a business requirements doc.",
    },
    "consultant": {
        "label": "Strategy consultant",
        "baseline_minutes": 480,  # 8 hrs: research + memo + iteration
        "description": "Strategy / management consultant building a client memo.",
    },
}

DEFAULT_PERSONA = "founder"

# Run-tag taxonomies. Keep these short — the goal is filterability, not nuance.
SECTORS = [
    "consumer",
    "b2b_saas",
    "fintech",
    "healthtech",
    "deeptech",
    "climate",
    "marketplaces",
    "infra_devtools",
    "ai_ml",
    "other",
]
STAGES = ["pre_seed", "seed", "series_a", "series_b_plus", "growth", "unspecified"]


def normalize_sector(value: str | None) -> str:
    v = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in SECTORS else "other"


def normalize_stage(value: str | None) -> str:
    v = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if v in {"preseed", "pre_seed"}:
        return "pre_seed"
    return v if v in STAGES else "unspecified"

# Admin gate: only these user_ids see the Admin tab.
# Override via env var ADMIN_EMAILS (comma-separated) if needed.
import os
_default_admin = "abhimanyu@nurix.ai"
ADMIN_EMAILS = {
    e.strip().lower()
    for e in (os.getenv("ADMIN_EMAILS") or _default_admin).split(",")
    if e.strip()
}


def is_admin(user_id: str | None) -> bool:
    if not user_id:
        return False
    return user_id.strip().lower() in ADMIN_EMAILS


def normalize_persona(value: str | None) -> str:
    """Coerce any incoming persona string to a known key, falling back to default."""
    if not value:
        return DEFAULT_PERSONA
    v = value.strip().lower()
    return v if v in PERSONAS else DEFAULT_PERSONA


def baseline_minutes(persona: str | None) -> int:
    return PERSONAS[normalize_persona(persona)]["baseline_minutes"]
