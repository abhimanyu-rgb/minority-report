"""Cross-run learning: flag-pattern memory + analytics aggregations.

Reads run.json + per-iteration premortems + feedback.json from every run under
runs/, builds priors for the premortem prompt, and computes analytics rollups.

Storage: runs/_index/flag_patterns.json — rebuilt incrementally at end of each
run and whenever feedback is submitted. Pure file-based; no DB.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
INDEX_DIR = RUNS_DIR / "_index"
PATTERNS_PATH = INDEX_DIR / "flag_patterns.json"

# Feedback gating: until at least this many runs have feedback, don't filter
# 👎 runs out of the priors — there's not enough signal yet.
FEEDBACK_GATE_N = 10

# How many priors to inject into the premortem prompt by default.
DEFAULT_PRIORS_TOP_N = 6

# A pattern must appear in at least this fraction of contributing runs to count
# as a "recurring" failure mode (also requires a minimum absolute count).
MIN_PATTERN_FRACTION = 0.10
MIN_PATTERN_COUNT = 2


def _wilson_lower_bound(successes: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for a binomial proportion.

    Gives a conservative estimate of the true rate that won't get fooled by
    small samples. With n=0 returns 0. With successes=0 the bound is still
    above 0 but small. We use this for flag-pattern predictiveness ranking.
    """
    if n <= 0:
        return 0.0
    p_hat = successes / n
    denom = 1 + (z * z) / n
    centre = (p_hat + (z * z) / (2 * n)) / denom
    margin = (z * (((p_hat * (1 - p_hat) / n) + (z * z) / (4 * n * n)) ** 0.5)) / denom
    return max(0.0, centre - margin)


def _norm_key(section: str, title: str) -> str:
    """Cluster flag patterns by a coarsened (section, title) key.

    Lowercase, strip punctuation, collapse whitespace. Two flags titled
    'Monetization unclear' and 'monetization unclear.' become the same key.
    """
    s = re.sub(r"[^\w\s]", " ", (section or "").lower()).strip()
    t = re.sub(r"[^\w\s]", " ", (title or "").lower()).strip()
    s = re.sub(r"\s+", " ", s)
    t = re.sub(r"\s+", " ", t)
    return f"{s}::{t}"


def _load_run_dirs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    out = []
    for d in RUNS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        if (d / "run.json").is_file():
            out.append(d)
    return sorted(out)


def _load_feedback(run_dir: Path) -> dict | None:
    p = run_dir / "feedback.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _completed_runs_with_feedback_count() -> int:
    n = 0
    for d in _load_run_dirs():
        if _load_feedback(d) is not None:
            n += 1
    return n


def rebuild_flag_patterns() -> dict:
    """Walk all runs, aggregate flags into priors, persist to PATTERNS_PATH.

    Returns the patterns dict. Safe to call concurrently with reads — write
    is a single atomic replace.
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    feedback_count = _completed_runs_with_feedback_count()
    gate_active = feedback_count >= FEEDBACK_GATE_N

    # Per-key aggregate: counts, example issues/suggestions, contributing runs.
    # outcomes per flag: count of runs with a recorded "failure" outcome
    # (killed/declined/passed) vs "success" outcome (invested/built/advanced).
    # Pivoted is neutral.
    agg: dict[str, dict] = defaultdict(lambda: {
        "count": 0,
        "section": "",
        "title": "",
        "severities": Counter(),
        "examples": [],
        "runs": set(),
        "outcome_failure": 0,  # runs with this flag that ended in declined/passed/killed
        "outcome_success": 0,  # runs with this flag that ended in invested/built/advanced
        "outcome_known": 0,    # runs with this flag and any non-unset outcome
    })

    FAILURE_OUTCOMES = {"declined", "passed", "killed"}
    SUCCESS_OUTCOMES = {"invested", "built", "advanced"}

    total_runs_considered = 0

    for run_dir in _load_run_dirs():
        try:
            manifest = json.loads((run_dir / "run.json").read_text())
        except Exception:
            continue
        if manifest.get("status") != "completed":
            continue

        # Feedback gate — once it's active, drop 👎 runs.
        fb = _load_feedback(run_dir)
        if gate_active and fb is not None and fb.get("rating") == "down":
            continue

        total_runs_considered += 1
        run_id = manifest.get("run_id", run_dir.name)

        # Outcome label for this run (if any). Used to weight flag patterns
        # by predictiveness in Tier 1.1.
        outcome = None
        outcome_path = run_dir / "outcome.json"
        if outcome_path.is_file():
            try:
                outcome = (json.loads(outcome_path.read_text()) or {}).get("outcome")
            except Exception:
                pass
        is_failure = outcome in FAILURE_OUTCOMES
        is_success = outcome in SUCCESS_OUTCOMES
        is_known = is_failure or is_success

        final_pm_path = run_dir / "final-premortem.json"
        if not final_pm_path.is_file():
            continue
        try:
            pm = json.loads(final_pm_path.read_text())
        except Exception:
            continue

        for f in pm.get("flags", []) or []:
            section = f.get("section", "") or ""
            title = f.get("title", "") or ""
            if not title:
                continue
            key = _norm_key(section, title)
            slot = agg[key]
            slot["count"] += 1
            slot["section"] = section
            slot["title"] = title
            slot["severities"][f.get("severity", "yellow")] += 1
            slot["runs"].add(run_id)
            if is_known:
                slot["outcome_known"] += 1
                if is_failure:
                    slot["outcome_failure"] += 1
                elif is_success:
                    slot["outcome_success"] += 1
            if len(slot["examples"]) < 3 and f.get("issue"):
                slot["examples"].append({"run_id": run_id, "issue": f["issue"][:240]})

    # Threshold: pattern must appear in MIN_PATTERN_COUNT runs AND ≥ fraction.
    patterns = []
    for key, slot in agg.items():
        n_runs = len(slot["runs"])
        if n_runs < MIN_PATTERN_COUNT:
            continue
        if total_runs_considered and (n_runs / total_runs_considered) < MIN_PATTERN_FRACTION:
            continue
        dominant_sev = slot["severities"].most_common(1)[0][0] if slot["severities"] else "yellow"
        # Wilson lower bound on failure rate. With n known and k failures,
        # this gives a conservative lower bound on P(failure | this flag fired).
        # When n is small, the bound shrinks toward 0.5 — keeps us from
        # over-claiming on 1/1 data.
        fail_rate = _wilson_lower_bound(slot["outcome_failure"], slot["outcome_known"])
        # Predictiveness: higher = flag has historically predicted failure.
        # Range [0, 1]. Used as the ranking signal once we have outcome data.
        predictiveness = round(fail_rate, 4)
        patterns.append({
            "key": key,
            "section": slot["section"],
            "title": slot["title"],
            "count": slot["count"],
            "run_count": n_runs,
            "dominant_severity": dominant_sev,
            "fraction_of_runs": round(n_runs / total_runs_considered, 4) if total_runs_considered else 0.0,
            "outcome_failure": slot["outcome_failure"],
            "outcome_success": slot["outcome_success"],
            "outcome_known": slot["outcome_known"],
            "predictiveness": predictiveness,
            "examples": slot["examples"],
        })

    # Rank: when outcome data is meaningful (≥3 patterns with ≥3 known
    # outcomes), use predictiveness × run_count as the sort key. Otherwise
    # fall back to volume-based ranking.
    outcome_coverage = sum(1 for p in patterns if p["outcome_known"] >= 3)
    if outcome_coverage >= 3:
        patterns.sort(key=lambda p: (-p["predictiveness"] * p["run_count"], -p["run_count"]))
    else:
        patterns.sort(key=lambda p: (-p["run_count"], -p["count"]))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_runs_considered": total_runs_considered,
        "feedback_runs": feedback_count,
        "feedback_gate_active": gate_active,
        "patterns": patterns,
    }

    tmp_path = PATTERNS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(out, indent=2))
    tmp_path.replace(PATTERNS_PATH)
    return out


def load_flag_patterns() -> dict:
    if not PATTERNS_PATH.is_file():
        return {"patterns": [], "total_runs_considered": 0, "feedback_gate_active": False}
    try:
        return json.loads(PATTERNS_PATH.read_text())
    except Exception:
        return {"patterns": [], "total_runs_considered": 0, "feedback_gate_active": False}


def get_premortem_priors_block(top_n: int = DEFAULT_PRIORS_TOP_N) -> str:
    """Return the formatted '## Historical failure patterns' block to inject
    into the premortem user prompt. Empty string if too few runs / no signal.
    """
    from .prompts import PREMORTEM_PRIORS_BLOCK

    data = load_flag_patterns()
    pats = data.get("patterns", [])[:top_n]
    if not pats or data.get("total_runs_considered", 0) < 3:
        # Not enough corpus yet — don't inject anything.
        return ""

    lines = []
    for i, p in enumerate(pats, 1):
        sev = p["dominant_severity"].upper()
        sec = p["section"] or "(unspecified)"
        outcome_known = p.get("outcome_known", 0)
        # Outcome-grounded note: only emit if we have ≥2 known outcomes for this flag.
        outcome_note = ""
        if outcome_known >= 2:
            fail = p.get("outcome_failure", 0)
            outcome_note = (
                f" Of prior runs with this flag and a known outcome, "
                f"{fail}/{outcome_known} ended in failure (declined / passed / killed)."
            )
        lines.append(
            f"{i}. **{p['title']}** — section: {sec} — severity historically: {sev} — "
            f"seen in {p['run_count']}/{data['total_runs_considered']} prior runs.{outcome_note}"
        )
    patterns_block = "\n".join(lines)
    return PREMORTEM_PRIORS_BLOCK.format(patterns=patterns_block)


# ----------------------------------------------------------------------------
# ANALYTICS
# ----------------------------------------------------------------------------

def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def compute_analytics(user_id: str | None = None, persona: str | None = None, mode: str = "admin") -> dict:
    """Roll up everything an analytics tab needs in a single pass.

    Args:
      user_id: if set, only include runs whose attribution.user_id matches.
      persona: if set, only include runs whose attribution.persona matches.
      mode: 'admin' (default, ops view) or 'user' (adds time-saved + per-user framing).
    """
    from .personas import baseline_minutes, PERSONAS

    runs: list[dict] = []
    for run_dir in _load_run_dirs():
        try:
            m = json.loads((run_dir / "run.json").read_text())
        except Exception:
            continue
        attr = m.get("attribution") or {}
        if user_id and (attr.get("user_id") or "anonymous") != user_id:
            continue
        if persona and (attr.get("persona") or "founder") != persona:
            continue
        fb = _load_feedback(run_dir)
        runs.append({"manifest": m, "feedback": fb, "dir": run_dir})

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    total_runs = 0
    completed = 0
    green_lit = 0
    cap_hit = 0  # completed runs that ran out of iterations without green-lighting
    total_cost = 0.0
    scores: list[tuple[datetime, int]] = []  # (started_at, final_score)
    feedback_up = 0
    feedback_down = 0
    feedback_acted = 0
    feedback_notes: list[dict] = []
    flag_titles: Counter[str] = Counter()

    # User-tab accumulators
    time_saved_minutes = 0
    recent_run_list: list[dict] = []
    persona_counts: Counter[str] = Counter()

    # New KPI accumulators
    completed_costs: list[float] = []          # per-completed-run total cost
    iter_costs: list[float] = []               # per-iteration cost (across all completed runs)
    iter_counts: list[int] = []                # iterations per completed run
    iter_counts_green: list[int] = []          # iterations per green-lit run only
    wall_seconds: list[float] = []             # per-completed-run wall clock
    iter_seconds: list[float] = []             # per-iteration wall clock
    score_lifts: list[int] = []                # final_score - iter1_score (multi-iter runs only)
    pauses_total = 0
    pauses_with_guidance = 0
    guidance_lengths: list[int] = []

    bucket_today = {"runs": 0, "cost": 0.0}
    bucket_week = {"runs": 0, "cost": 0.0}
    bucket_month = {"runs": 0, "cost": 0.0}

    for r in runs:
        m = r["manifest"]
        total_runs += 1
        cost = float(((m.get("cost") or {}).get("total_usd")) or 0.0)
        total_cost += cost
        started = _parse_iso(m.get("started_at"))
        if started:
            if started >= today_start:
                bucket_today["runs"] += 1
                bucket_today["cost"] += cost
            if started >= week_start:
                bucket_week["runs"] += 1
                bucket_week["cost"] += cost
            if started >= month_start:
                bucket_month["runs"] += 1
                bucket_month["cost"] += cost
        if m.get("status") == "completed":
            completed += 1
            iters = m.get("iterations") or []
            n_iters = m.get("total_iterations") or len(iters)
            iter_counts.append(n_iters)
            if m.get("green_lit"):
                green_lit += 1
                iter_counts_green.append(n_iters)
            else:
                # cap_hit = completed but not green-lit AND hit the max
                max_iter = ((m.get("settings") or {}).get("max_iterations")) or 0
                if max_iter and n_iters >= max_iter:
                    cap_hit += 1
            fs = m.get("final_score")
            if fs is not None and started:
                scores.append((started, int(fs)))
            # Cost stats (schema v2+ runs only have m['cost'])
            if cost > 0:
                completed_costs.append(cost)
            # Wall clock — overall + per iteration
            finished = _parse_iso(m.get("finished_at"))
            if started and finished and finished >= started:
                wall_seconds.append((finished - started).total_seconds())
            for it in iters:
                ic = it.get("cost_usd")
                if isinstance(ic, (int, float)) and ic > 0:
                    iter_costs.append(float(ic))
                bs = _parse_iso(it.get("brainstorm_started_at"))
                pe = _parse_iso(it.get("premortem_finished_at"))
                if bs and pe and pe >= bs:
                    iter_seconds.append((pe - bs).total_seconds())
            # Score lift (multi-iter runs only)
            if len(iters) >= 2 and iters[0].get("score") is not None and fs is not None:
                score_lifts.append(int(fs) - int(iters[0]["score"]))
            # Pause engagement
            for it in iters[:-1]:  # last iteration never pauses
                pauses_total += 1
                if it.get("had_guidance_after"):
                    pauses_with_guidance += 1
            # Guidance text length (read from idea sidecar — we kept the text in iter dirs)
            # Best-effort: look at iter.json files
            for it in iters:
                if it.get("had_guidance_after"):
                    iter_dir = r["dir"] / "iterations" / it.get("iteration_id", "")
                    g_path = iter_dir / "guidance.txt"
                    if g_path.is_file():
                        try:
                            guidance_lengths.append(len(g_path.read_text().strip()))
                        except Exception:
                            pass
        # Flag titles from per-iteration sidecars wouldn't add much extra
        # signal here; use the final premortem.
        final_pm_path = r["dir"] / "final-premortem.json"
        if final_pm_path.is_file():
            try:
                pm = json.loads(final_pm_path.read_text())
                for f in pm.get("flags", []) or []:
                    if f.get("title"):
                        flag_titles[f["title"]] += 1
            except Exception:
                pass

        fb = r["feedback"]
        if fb is not None:
            rating = fb.get("rating")
            if rating == "up":
                feedback_up += 1
            elif rating == "down":
                feedback_down += 1
            elif rating == "acted_on":
                feedback_acted += 1
            if fb.get("note"):
                feedback_notes.append({
                    "run_id": m.get("run_id"),
                    "rating": rating,
                    "note": fb["note"],
                    "submitted_at": fb.get("submitted_at"),
                })

        # Time-saved + recent-runs accumulators (completed runs only).
        if m.get("status") == "completed":
            attr = m.get("attribution") or {}
            run_persona = attr.get("persona") or "founder"
            persona_counts[run_persona] += 1
            base = baseline_minutes(run_persona)
            finished = _parse_iso(m.get("finished_at"))
            actual_min = 0
            if started and finished and finished >= started:
                actual_min = (finished - started).total_seconds() / 60.0
            saved = max(0, base - actual_min)
            time_saved_minutes += saved
            recent_run_list.append({
                "run_id": m.get("run_id"),
                "started_at": m.get("started_at"),
                "final_score": m.get("final_score"),
                "green_lit": m.get("green_lit"),
                "total_iterations": m.get("total_iterations"),
                "persona": run_persona,
                "user_id": attr.get("user_id") or "anonymous",
                "cost_usd": cost,
                "feedback": (r["feedback"] or {}).get("rating"),
            })

    # Score distribution buckets (10-wide).
    dist = [0] * 10  # 0–9, 10–19, ..., 90–100
    for _, s in scores:
        idx = min(9, max(0, s // 10))
        dist[idx] += 1

    # Rolling 7-day mean for the last 30 days.
    scores.sort(key=lambda x: x[0])
    daily_means: list[dict] = []
    if scores:
        first_day = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        for offset in range(30):
            day = first_day + timedelta(days=offset)
            window_start = day - timedelta(days=6)
            window_end = day + timedelta(days=1)
            window_scores = [s for (ts, s) in scores if window_start <= ts < window_end]
            mean = round(sum(window_scores) / len(window_scores), 2) if window_scores else None
            daily_means.append({
                "date": day.date().isoformat(),
                "rolling_mean_7d": mean,
                "n": len(window_scores),
            })

    def _pct(num, denom):
        return round((num / denom) * 100, 1) if denom else 0.0

    def _avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    def _pctl(xs, q):
        if not xs:
            return None
        s = sorted(xs)
        k = max(0, min(len(s) - 1, int(round((q / 100.0) * (len(s) - 1)))))
        return round(s[k], 4)

    avg_final_score = _avg([s for _, s in scores])
    avg_iters = _avg([float(x) for x in iter_counts])
    avg_iters_green = _avg([float(x) for x in iter_counts_green])

    return {
        "generated_at": now.isoformat(),
        "totals": {
            "all_time": {"runs": total_runs, "completed": completed, "green_lit": green_lit, "cost_usd": round(total_cost, 6)},
            "today": {"runs": bucket_today["runs"], "cost_usd": round(bucket_today["cost"], 6)},
            "this_week": {"runs": bucket_week["runs"], "cost_usd": round(bucket_week["cost"], 6)},
            "this_month": {"runs": bucket_month["runs"], "cost_usd": round(bucket_month["cost"], 6)},
        },
        "cost_kpis": {
            "avg_cost_per_run": _avg(completed_costs),
            "p50_cost_per_run": _pctl(completed_costs, 50),
            "p95_cost_per_run": _pctl(completed_costs, 95),
            "max_cost_per_run": max(completed_costs) if completed_costs else None,
            "min_cost_per_run": min(completed_costs) if completed_costs else None,
            "avg_cost_per_iteration": _avg(iter_costs),
            "sample_size_runs": len(completed_costs),
            "sample_size_iters": len(iter_costs),
        },
        "quality_kpis": {
            "green_light_rate_pct": _pct(green_lit, completed),
            "cap_hit_rate_pct": _pct(cap_hit, completed),
            "avg_final_score": avg_final_score,
            "avg_iterations_all": avg_iters,
            "avg_iterations_green_lit": avg_iters_green,
            "avg_score_lift_v1_to_final": _avg([float(x) for x in score_lifts]),
            "score_lift_sample": len(score_lifts),
        },
        "engagement_kpis": {
            "pauses_total": pauses_total,
            "pauses_with_guidance": pauses_with_guidance,
            "guidance_rate_pct": _pct(pauses_with_guidance, pauses_total),
            "avg_guidance_chars": _avg([float(x) for x in guidance_lengths]),
        },
        "speed_kpis": {
            "avg_seconds_per_run": _avg(wall_seconds),
            "p50_seconds_per_run": _pctl(wall_seconds, 50),
            "p95_seconds_per_run": _pctl(wall_seconds, 95),
            "avg_seconds_per_iteration": _avg(iter_seconds),
        },
        "score_distribution": dist,
        "rolling_mean_7d": daily_means,
        "feedback": {
            "up": feedback_up,
            "down": feedback_down,
            "acted_on": feedback_acted,
            "total": feedback_up + feedback_down + feedback_acted,
            "recent_notes": sorted(feedback_notes, key=lambda x: x.get("submitted_at") or "", reverse=True)[:10],
        },
        "user_kpis": {
            "reports_completed": completed,
            "reports_this_month": bucket_month["runs"],
            "reports_this_week": bucket_week["runs"],
            "time_saved_minutes": round(time_saved_minutes, 1),
            "time_saved_hours": round(time_saved_minutes / 60.0, 1),
            "acted_on_count": feedback_acted,
            "acted_on_rate_pct": _pct(feedback_acted, completed),
            "green_light_rate_pct": _pct(green_lit, completed),
            "decision_velocity_per_week": round(bucket_week["runs"], 1),
            "score_progression": [
                {"date": ts.date().isoformat(), "score": s}
                for (ts, s) in sorted(scores)
            ][-20:],  # last 20 runs
            "recent_runs": sorted(
                recent_run_list, key=lambda x: x.get("started_at") or "", reverse=True
            )[:15],
            "persona_mix": dict(persona_counts),
        },
        "top_flags": [
            {"title": t, "count": c}
            for t, c in flag_titles.most_common(10)
        ],
        "flag_patterns_meta": {
            **{k: v for k, v in load_flag_patterns().items() if k != "patterns"},
            "pattern_count": len(load_flag_patterns().get("patterns", [])),
        },
    }
