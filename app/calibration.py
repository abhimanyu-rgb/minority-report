"""Per-user calibration — learn from how a user *responds* to flags.

When the premortem fires a yellow/red flag and the user's strategic guidance
either acknowledges it ("yes, address this") or pushes back ("this isn't
material to my thesis"), that's signal. Over time the system can learn:
  - User X consistently overrides 'moat unclear' flags -> de-weight that
    pattern's priors in *their* premortem prompts.
  - User Y consistently flags 'monetization model fuzzy' as critical -> bias
    the premortem to elevate that.

This module is data-layer scaffolding. The actual signal extraction (e.g.
NLP over guidance text) can grow in sophistication later. We start with
a simple keyword-match heuristic.

Storage: app/data/user_calibration.json — {user_id: {flag_key: {override: int, reinforce: int}}}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CAL_PATH = Path(__file__).resolve().parent / "data" / "user_calibration.json"

# Light heuristic: terms suggesting the user is dismissing / pushing back vs reinforcing.
_OVERRIDE_TERMS = re.compile(
    r"\b(ignore|not (?:material|relevant|important)|already addressed|out of scope|don'?t (?:agree|care)|"
    r"skip|drop|too early|noise|misread)\b",
    re.IGNORECASE,
)
_REINFORCE_TERMS = re.compile(
    r"\b(yes|exactly|important|critical|address|fix|need to|must (?:address|fix|solve)|priority|good catch)\b",
    re.IGNORECASE,
)


def _load() -> dict:
    if not CAL_PATH.is_file():
        return {}
    try:
        return json.loads(CAL_PATH.read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CAL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(CAL_PATH)


def get_user_calibration(user_id: str | None) -> dict:
    if not user_id:
        return {}
    return _load().get(user_id.strip().lower(), {})


def record_interaction(user_id: str, flag_key: str, guidance_text: str) -> None:
    """Update the user's calibration counters based on guidance vs a flag."""
    user_id = (user_id or "").strip().lower()
    guidance_text = (guidance_text or "").strip()
    if not user_id or not flag_key or not guidance_text:
        return
    is_override = bool(_OVERRIDE_TERMS.search(guidance_text))
    is_reinforce = bool(_REINFORCE_TERMS.search(guidance_text))
    if not (is_override or is_reinforce):
        return
    store = _load()
    user_slot = store.setdefault(user_id, {})
    flag_slot = user_slot.setdefault(flag_key, {"override": 0, "reinforce": 0})
    if is_override:
        flag_slot["override"] = int(flag_slot.get("override", 0)) + 1
    if is_reinforce:
        flag_slot["reinforce"] = int(flag_slot.get("reinforce", 0)) + 1
    _save(store)


def calibration_block(user_id: str | None) -> str:
    """Return a prompt block summarising the user's flag-response pattern.

    Empty when the user has no calibration history yet. The block is injected
    into the premortem alongside the universal priors so the model can soften
    or sharpen its sensitivity per-user.
    """
    cal = get_user_calibration(user_id)
    # Only emit if the user has a non-trivial history.
    items = [(k, v) for k, v in cal.items() if (v.get("override", 0) + v.get("reinforce", 0)) >= 2]
    if not items:
        return ""
    # Surface the strongest patterns: highest |override - reinforce|.
    items.sort(key=lambda kv: -abs(kv[1].get("override", 0) - kv[1].get("reinforce", 0)))
    items = items[:6]
    lines = []
    for key, counts in items:
        o = counts.get("override", 0)
        r = counts.get("reinforce", 0)
        nice_title = key.split("::", 1)[-1] if "::" in key else key
        if o > r:
            tendency = f"de-prioritizes this concern (overridden {o}× vs reinforced {r}× in past runs)"
        elif r > o:
            tendency = f"treats this as critical (reinforced {r}× vs overridden {o}× in past runs)"
        else:
            continue
        lines.append(f"- **{nice_title}** — user historically {tendency}.")
    if not lines:
        return ""
    return (
        "\n## User-specific calibration\n"
        "The reviewer for this BRD has shown the following response patterns to past flags:\n\n"
        + "\n".join(lines)
        + "\n\nFactor this into severity calibration only — never silently drop a flag the BRD actually warrants.\n"
    )
