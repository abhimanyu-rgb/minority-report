"""Cross-run feedback analysis — product-improvement insights for the operator.

Loads every run's feedback.json + run.json, joins them into a corpus, and
asks Sonnet to extract themes / complaints / praises / recommended actions.

Caches the result to runs/_index/feedback_analysis.json so revisits are free
between actual analyses. A 'stale' flag signals when more feedback has come
in since the last analysis.

Separate from Wave C (premortem flag-pattern memory). That tunes the model.
This one talks to the operator about what to change in the *product*.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from anthropic import AsyncAnthropic

from .models_cfg import MODELS, usage_from_response

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
INDEX_DIR = RUNS_DIR / "_index"
CACHE_PATH = INDEX_DIR / "feedback_analysis.json"

# Minimum feedback ratings before we'll even attempt analysis. Below this the
# LLM has too little signal and will hallucinate themes.
MIN_FEEDBACK_COUNT = 5

# Default model for the analysis itself. Reuses the evolution/refine tier.
ANALYSIS_MODEL_KEY = "refine"  # reuses existing config; Sonnet by default


ANALYSIS_SYSTEM = """You analyze user feedback on AI-generated business requirements documents (BRDs) to surface product-improvement insights for the operator running this app.

You will receive a corpus of feedback records. Each record has:
  - rating: 'up' (useful) / 'down' (off-base) / 'acted_on' (user took action)
  - note: free-text comment from the user (may be empty)
  - run metadata: sector, stage, persona, final_score, green_lit, outcome (if marked)
  - top_flags: the premortem flags fired on that run

Your job:

1. Identify recurring **themes** — patterns of feedback that appear ≥2 times. For each, name it crisply (3-6 words), say which runs cluster under it (list run_ids), and quote the strongest representative note.

2. Sentiment **distribution** — count of up / down / acted_on. Plus a one-line read on the overall sentiment.

3. Top **complaints** — issues the user wants fixed. Rank by frequency × severity. For each: what's wrong, evidence (quoted note fragments + run_ids), and how confident you are this is a real pattern vs a one-off.

4. Top **praises** — what's clearly working. Use these to flag features NOT to break.

5. **Recommended actions** — concrete product changes ranked by impact. Each must:
   - Name a specific feature, prompt, or behavior to change
   - Cite the feedback evidence behind it
   - Estimate effort (small / medium / large)
   - Note any risk (what could break, who'd be unhappy)

Be honest. If the corpus is too thin to support a claim, say so — better to mark something 'low confidence — only seen in 2 runs' than to overgeneralize. Don't invent themes. Don't soften complaints.

Output strict JSON in the schema below. No prose outside the JSON.

```json
{
  "summary": "1-2 sentence read on the corpus",
  "sentiment": {"up": int, "down": int, "acted_on": int, "total": int, "overall": "positive|mixed|negative"},
  "themes": [
    {"name": "...", "frequency": int, "example_run_ids": [...], "representative_note": "..."}
  ],
  "complaints": [
    {"issue": "...", "confidence": "high|medium|low", "evidence_run_ids": [...], "example_quotes": [...]}
  ],
  "praises": [
    {"strength": "...", "evidence_run_ids": [...], "example_quotes": [...]}
  ],
  "recommended_actions": [
    {"action": "...", "rationale": "...", "effort": "small|medium|large", "risk": "...", "supporting_run_ids": [...]}
  ]
}
```
"""

ANALYSIS_USER = """Feedback corpus ({n} records):

{corpus}

Output the JSON analysis now. JSON only."""


def _load_feedback_record(run_dir: Path) -> dict | None:
    fb_path = run_dir / "feedback.json"
    if not fb_path.is_file():
        return None
    try:
        return json.loads(fb_path.read_text())
    except Exception:
        return None


def _gather_corpus() -> tuple[list[dict], int]:
    """Walk all runs and assemble [{feedback record + run metadata + top flags}].

    Returns (records, total_feedback_count). Sorted oldest-first so the LLM
    sees the temporal arc, not just the latest noise.
    """
    out: list[dict] = []
    if not RUNS_DIR.exists():
        return [], 0
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("_"):
            continue
        fb = _load_feedback_record(run_dir)
        if fb is None:
            continue
        manifest = None
        try:
            manifest = json.loads((run_dir / "run.json").read_text())
        except Exception:
            pass
        if manifest is None:
            continue
        attr = manifest.get("attribution") or {}
        # Pull final premortem flags (top 4 by severity)
        top_flags: list[dict] = []
        pm_path = run_dir / "final-premortem.json"
        if pm_path.is_file():
            try:
                pm = json.loads(pm_path.read_text())
                order = {"red": 0, "yellow": 1, "green": 2}
                flags = sorted(pm.get("flags", []) or [], key=lambda f: order.get(f.get("severity", ""), 3))
                top_flags = [
                    {"severity": f.get("severity"), "title": f.get("title"), "section": f.get("section")}
                    for f in flags[:4]
                ]
            except Exception:
                pass
        out.append({
            "run_id": manifest.get("run_id") or run_dir.name,
            "submitted_at": fb.get("submitted_at"),
            "rating": fb.get("rating"),
            "note": (fb.get("note") or "").strip(),
            "most_useful_iteration_n": fb.get("most_useful_iteration_n"),
            "sector": attr.get("sector"),
            "stage": attr.get("stage"),
            "persona": attr.get("persona"),
            "final_score": manifest.get("final_score"),
            "green_lit": manifest.get("green_lit"),
            "outcome": ((_load_outcome(run_dir) or {}).get("outcome")),
            "top_flags": top_flags,
        })
    return out, len(out)


def _load_outcome(run_dir: Path) -> dict | None:
    p = run_dir / "outcome.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def feedback_status() -> dict:
    """Quick status check: counts + whether cached analysis is stale."""
    _records, count = _gather_corpus()
    cached = load_cached_analysis()
    stale = False
    new_since_cache = 0
    if cached:
        new_since_cache = count - (cached.get("feedback_count_at_analysis") or 0)
        stale = new_since_cache >= 5  # auto-refresh threshold
    return {
        "feedback_count": count,
        "min_required": MIN_FEEDBACK_COUNT,
        "ready": count >= MIN_FEEDBACK_COUNT,
        "cached_at": (cached or {}).get("generated_at"),
        "feedback_count_at_analysis": (cached or {}).get("feedback_count_at_analysis"),
        "new_since_cache": new_since_cache,
        "stale": stale,
    }


def load_cached_analysis() -> dict | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None


def _save_cache(payload: dict) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(CACHE_PATH)


def _extract_json(text: str) -> dict:
    import re
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in response.")
    return json.loads(text[start : end + 1])


async def analyze(client: AsyncAnthropic | None = None) -> dict:
    """Run the analysis and cache the result.

    Raises ValueError if there are fewer than MIN_FEEDBACK_COUNT records.
    """
    records, count = _gather_corpus()
    if count < MIN_FEEDBACK_COUNT:
        raise ValueError(
            f"Not enough feedback yet: {count} / {MIN_FEEDBACK_COUNT} required. "
            f"Gather more thumbs-up / thumbs-down ratings before analyzing."
        )

    # Pre-compute sentiment so the LLM doesn't have to (and can't miscount).
    sentiment = Counter(r["rating"] for r in records if r["rating"] in ("up", "down", "acted_on"))
    sentiment_pre = {
        "up": sentiment.get("up", 0),
        "down": sentiment.get("down", 0),
        "acted_on": sentiment.get("acted_on", 0),
        "total": sum(sentiment.values()),
    }

    # Format the corpus compactly so we don't burn tokens on JSON noise.
    corpus_lines = []
    for r in records:
        flag_str = ", ".join(
            f"{f.get('severity','?').upper()}:{f.get('title','')}"
            for f in (r.get("top_flags") or [])
        ) or "(no flags)"
        corpus_lines.append(json.dumps({
            "run_id": r["run_id"],
            "submitted_at": r["submitted_at"],
            "rating": r["rating"],
            "note": r["note"],
            "sector": r["sector"],
            "stage": r["stage"],
            "persona": r["persona"],
            "final_score": r["final_score"],
            "green_lit": r["green_lit"],
            "outcome": r["outcome"],
            "top_flags": flag_str,
            "most_useful_iteration_n": r["most_useful_iteration_n"],
        }, ensure_ascii=False))
    corpus = "\n".join(corpus_lines)

    c = client or AsyncAnthropic()
    model = MODELS.get(ANALYSIS_MODEL_KEY) or "claude-sonnet-4-6"
    resp = await c.messages.create(
        model=model,
        max_tokens=4000,
        system=ANALYSIS_SYSTEM,
        messages=[{"role": "user", "content": ANALYSIS_USER.format(n=count, corpus=corpus)}],
    )
    raw = resp.content[0].text
    try:
        parsed = _extract_json(raw)
    except Exception as e:
        raise RuntimeError(f"Could not parse analysis JSON: {e}\n\n{raw[:600]}") from e
    usage = usage_from_response(model, resp)

    # Force-correct the sentiment block against the pre-computed truth so the
    # LLM can't miscount. Keep its 'overall' read since that's qualitative.
    parsed_sentiment = parsed.get("sentiment") or {}
    parsed_sentiment.update(sentiment_pre)
    parsed["sentiment"] = parsed_sentiment

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feedback_count_at_analysis": count,
        "model": model,
        "cost_usd": round(usage.cost_usd, 6),
        "tokens": {"input": usage.input_tokens, "output": usage.output_tokens},
        "analysis": parsed,
    }
    _save_cache(payload)
    return payload
