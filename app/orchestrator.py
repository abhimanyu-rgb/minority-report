"""Recursive brainstorm -> premortem loop.

Stop rule: score >= SCORE_THRESHOLD AND zero red flags.
Cap: MAX_ITERATIONS. If cap is hit without green-light, the best-scoring
iteration is published with a warning banner.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from anthropic import AsyncAnthropic

from .prompts import (
    BRAINSTORM_SYSTEM,
    BRAINSTORM_INITIAL_USER,
    BRAINSTORM_REVISION_USER,
    EVOLUTION_SYSTEM,
    EVOLUTION_USER,
    PREMORTEM_SYSTEM,
    PREMORTEM_USER,
    USER_GUIDANCE_BLOCK,
    VC_MATCH_SYSTEM,
    VC_MATCH_USER,
    VC_EVAL_SYSTEM,
    VC_EVAL_USER,
    VC_CONSENSUS_SYSTEM,
    VC_CONSENSUS_USER,
)

VC_PROFILES_PATH = Path(__file__).resolve().parent / "data" / "vc_profiles.json"

# Callable the HTTP layer injects to pause the loop between iterations.
# Returns the user's guidance text (empty string == skip).
GuidanceFn = Callable[[int, list[dict]], Awaitable[str]]

BRAINSTORM_MODEL = os.getenv("BRAINSTORM_MODEL", "claude-sonnet-4-6")
PREMORTEM_MODEL = os.getenv("PREMORTEM_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "5"))
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "80"))

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)


@dataclass
class Flag:
    severity: str
    section: str
    title: str
    issue: str
    suggestion: str


@dataclass
class Premortem:
    score: int
    verdict: str
    summary: str
    flags: list[Flag] = field(default_factory=list)

    @property
    def red_count(self) -> int:
        return sum(1 for f in self.flags if f.severity == "red")

    @property
    def yellow_count(self) -> int:
        return sum(1 for f in self.flags if f.severity == "yellow")

    def is_green_lit(self) -> bool:
        return self.score >= SCORE_THRESHOLD and self.red_count == 0


@dataclass
class Iteration:
    n: int
    brd: str
    premortem: Premortem
    user_guidance_after: str = ""  # guidance the user provided AFTER this iteration's premortem


def _event(type_: str, **data) -> dict:
    return {"event": type_, "data": data}


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of model output, tolerating fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Greedy match from first { to last }.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in:\n{text[:500]}")
    return json.loads(text[start : end + 1])


def _top_strategic_issues(p: Premortem, k: int = 5) -> list[Flag]:
    """Pick the top k flags worth surfacing for human strategic input.

    Order: reds first (most severe), then yellows, then greens. Within each
    severity the model's order is preserved (it lists most-impactful first).
    """
    order = {"red": 0, "yellow": 1, "green": 2}
    return sorted(p.flags, key=lambda f: order.get(f.severity, 3))[:k]


def _format_premortem_for_revision(p: Premortem) -> str:
    lines = [f"Score: {p.score}/100. Verdict: {p.verdict}.", f"Summary: {p.summary}", ""]
    for sev in ("red", "yellow", "green"):
        bucket = [f for f in p.flags if f.severity == sev]
        if not bucket:
            continue
        lines.append(f"## {sev.upper()} flags")
        for f in bucket:
            lines.append(f"- **{f.title}** ({f.section})")
            lines.append(f"  - Issue: {f.issue}")
            lines.append(f"  - Suggestion: {f.suggestion}")
        lines.append("")
    return "\n".join(lines)


class Orchestrator:
    def __init__(self) -> None:
        self.client = AsyncAnthropic()

    async def _brainstorm(self, user_msg: str) -> str:
        resp = await self.client.messages.create(
            model=BRAINSTORM_MODEL,
            max_tokens=8000,
            system=BRAINSTORM_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text

    async def _vc_match(self, brd: str, vc_db: list[dict]) -> list[dict]:
        # Strip heavy fields the matcher does not need.
        compact = [
            {k: v for k, v in p.items() if k in ("id", "firm", "thesis", "what_they_fund", "sectors", "stage_focus")}
            for p in vc_db
        ]
        resp = await self.client.messages.create(
            model=PREMORTEM_MODEL,
            max_tokens=1500,
            system=VC_MATCH_SYSTEM,
            messages=[{
                "role": "user",
                "content": VC_MATCH_USER.format(brd=brd, vc_db=json.dumps(compact, indent=2)),
            }],
        )
        data = _extract_json(resp.content[0].text)
        matches = data.get("matches", [])
        # Resolve ids -> full profiles, preserving reason.
        by_id = {p["id"]: p for p in vc_db}
        resolved = []
        for m in matches[:3]:
            profile = by_id.get(m.get("id"))
            if profile is None:
                continue
            resolved.append({"profile": profile, "reason": m.get("reason", "")})
        return resolved

    async def _vc_eval(self, brd: str, profile: dict, final_score: int, final_summary: str) -> dict:
        resp = await self.client.messages.create(
            model=PREMORTEM_MODEL,
            max_tokens=3000,
            system=VC_EVAL_SYSTEM.format(profile=json.dumps(profile, indent=2)),
            messages=[{
                "role": "user",
                "content": VC_EVAL_USER.format(
                    brd=brd, final_score=final_score, final_premortem_summary=final_summary
                ),
            }],
        )
        return _extract_json(resp.content[0].text)

    async def _vc_consensus(self, memos: list[dict]) -> dict:
        # Strip massive fields, keep firm + verdict + valuations + key memo bullets.
        compact = []
        for m in memos:
            compact.append({
                "firm": m["profile"]["firm"],
                "verdict": m["eval"]["verdict"],
                "conviction": m["eval"]["conviction"],
                "would_lead": m["eval"]["would_lead"],
                "seed_valuation_low_usd": m["eval"]["seed_valuation_low_usd"],
                "seed_valuation_high_usd": m["eval"]["seed_valuation_high_usd"],
                "check_size_usd": m["eval"]["check_size_usd"],
                "what_we_like": m["eval"]["memo"]["what_we_like"],
                "what_concerns_us": m["eval"]["memo"]["what_concerns_us"],
                "deal_breakers": m["eval"]["memo"]["deal_breakers"],
                "valuation_rationale": m["eval"]["memo"]["valuation_rationale"],
            })
        resp = await self.client.messages.create(
            model=PREMORTEM_MODEL,
            max_tokens=1500,
            system=VC_CONSENSUS_SYSTEM,
            messages=[{
                "role": "user",
                "content": VC_CONSENSUS_USER.format(memos_block=json.dumps(compact, indent=2)),
            }],
        )
        return _extract_json(resp.content[0].text)

    async def _evolution_report(self, idea: str, iterations: list[Iteration], final: Iteration) -> str:
        blocks: list[str] = []
        for it in iterations:
            blocks.append(f"### Iteration {it.n}")
            blocks.append(f"**Premortem score:** {it.premortem.score} — verdict: {it.premortem.verdict}")
            blocks.append(f"**Premortem summary:** {it.premortem.summary}")
            blocks.append("")
            blocks.append("**BRD draft:**")
            blocks.append("```markdown")
            blocks.append(it.brd)
            blocks.append("```")
            blocks.append("")
            blocks.append("**Premortem flags:**")
            blocks.append(_format_premortem_for_revision(it.premortem))
            if it.user_guidance_after:
                blocks.append(f"**User strategic guidance after this iteration (drove iteration {it.n + 1}):**")
                blocks.append(f"> {it.user_guidance_after}")
            elif it.n < len(iterations):
                blocks.append("**User skipped strategic input after this iteration.**")
            blocks.append("")
        history_block = "\n".join(blocks)

        resp = await self.client.messages.create(
            model=BRAINSTORM_MODEL,
            max_tokens=4000,
            system=EVOLUTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": EVOLUTION_USER.format(
                    idea=idea,
                    history_block=history_block,
                    final_brd=final.brd,
                    final_score=final.premortem.score,
                    final_verdict=final.premortem.verdict,
                ),
            }],
        )
        return resp.content[0].text

    async def _premortem(self, brd: str) -> Premortem:
        resp = await self.client.messages.create(
            model=PREMORTEM_MODEL,
            max_tokens=4000,
            system=PREMORTEM_SYSTEM,
            messages=[{"role": "user", "content": PREMORTEM_USER.format(brd=brd)}],
        )
        raw = resp.content[0].text
        data = _extract_json(raw)
        flags = [Flag(**f) for f in data.get("flags", [])]
        return Premortem(
            score=int(data["score"]),
            verdict=data.get("verdict", "needs-revision"),
            summary=data.get("summary", ""),
            flags=flags,
        )

    async def run(
        self,
        idea: str,
        run_id: str,
        guidance_fn: GuidanceFn | None = None,
        max_iterations: int | None = None,
    ) -> AsyncIterator[dict]:
        max_iter = max(1, min(20, int(max_iterations if max_iterations is not None else DEFAULT_MAX_ITERATIONS)))
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "idea.txt").write_text(idea)

        yield _event("run_started", run_id=run_id, max_iterations=max_iter, threshold=SCORE_THRESHOLD)

        iterations: list[Iteration] = []
        previous_brd: str | None = None
        previous_premortem: Premortem | None = None
        pending_guidance: str = ""  # filled between iterations from user input

        for n in range(1, max_iter + 1):
            yield _event("iteration_started", n=n)

            if previous_brd is None:
                user_msg = BRAINSTORM_INITIAL_USER.format(idea=idea)
            else:
                guidance_block = (
                    USER_GUIDANCE_BLOCK.format(guidance=pending_guidance.strip())
                    if pending_guidance.strip()
                    else ""
                )
                user_msg = BRAINSTORM_REVISION_USER.format(
                    previous_brd=previous_brd,
                    premortem_summary=_format_premortem_for_revision(previous_premortem),
                    guidance_block=guidance_block,
                )

            yield _event("brainstorm_started", n=n)
            brd = await self._brainstorm(user_msg)
            (run_dir / f"brd-v{n}.md").write_text(brd)
            yield _event("brainstorm_done", n=n, brd=brd)

            yield _event("premortem_started", n=n)
            premortem = await self._premortem(brd)
            (run_dir / f"premortem-v{n}.json").write_text(json.dumps(_premortem_to_dict(premortem), indent=2))
            yield _event(
                "premortem_done",
                n=n,
                score=premortem.score,
                verdict=premortem.verdict,
                summary=premortem.summary,
                red_count=premortem.red_count,
                yellow_count=premortem.yellow_count,
                flags=[asdict(f) for f in premortem.flags],
            )

            iterations.append(Iteration(n=n, brd=brd, premortem=premortem))
            previous_brd = brd
            previous_premortem = premortem

            if premortem.is_green_lit():
                yield _event("green_lit", n=n, score=premortem.score)
                break

            if n == max_iter:
                yield _event("cap_hit", n=n)
                break

            # Strategic-pause: surface top issues, wait for user guidance (or skip).
            top_issues = [asdict(f) for f in _top_strategic_issues(premortem, k=5)]
            yield _event(
                "awaiting_input",
                n=n,
                next_iteration=n + 1,
                top_issues=top_issues,
                score=premortem.score,
            )
            if guidance_fn is not None:
                pending_guidance = await guidance_fn(n, top_issues)
            else:
                pending_guidance = ""
            iterations[-1].user_guidance_after = pending_guidance.strip()
            if pending_guidance.strip():
                (run_dir / f"guidance-after-v{n}.txt").write_text(pending_guidance)
                yield _event("guidance_received", n=n, guidance=pending_guidance)
            else:
                yield _event("guidance_skipped", n=n)

        # Pick final: latest if green-lit, else best-scoring.
        if iterations[-1].premortem.is_green_lit():
            final = iterations[-1]
            warning = None
        else:
            final = max(iterations, key=lambda it: it.premortem.score)
            warning = (
                f"Did not meet the bar (score ≥ {SCORE_THRESHOLD} and zero red flags) "
                f"after {len(iterations)} iterations. Publishing the best-scoring draft "
                f"(iteration {final.n}, score {final.premortem.score}). "
                f"Remaining red flags: {final.premortem.red_count}."
            )

        (run_dir / "final-brd.md").write_text(final.brd)
        (run_dir / "final-premortem.json").write_text(json.dumps(_premortem_to_dict(final.premortem), indent=2))

        yield _event("evolution_report_started")
        try:
            evolution_report = await self._evolution_report(idea, iterations, final)
        except Exception as e:
            evolution_report = f"# Evolution Report\n\nFailed to generate: {e}"
        (run_dir / "evolution-report.md").write_text(evolution_report)
        yield _event("evolution_report_done", report=evolution_report)

        # VC consideration stage: match top 3 firms, run partner memos in parallel, synthesize consensus.
        vc_data: dict | None = None
        try:
            yield _event("vc_stage_started")
            vc_db = json.loads(VC_PROFILES_PATH.read_text())
            yield _event("vc_matching")
            matched = await self._vc_match(final.brd, vc_db)
            yield _event(
                "vc_matched",
                matches=[{"firm": m["profile"]["firm"], "id": m["profile"]["id"], "reason": m["reason"]} for m in matched],
            )

            yield _event("vc_evaluating", count=len(matched))
            evals = await asyncio.gather(
                *[self._vc_eval(final.brd, m["profile"], final.premortem.score, final.premortem.summary) for m in matched],
                return_exceptions=True,
            )
            memos: list[dict] = []
            for m, e in zip(matched, evals):
                if isinstance(e, Exception):
                    yield _event("vc_eval_error", firm=m["profile"]["firm"], message=str(e))
                    continue
                memos.append({"profile": m["profile"], "match_reason": m["reason"], "eval": e})
                yield _event("vc_eval_done", firm=m["profile"]["firm"], eval=e, match_reason=m["reason"], profile=m["profile"])

            consensus = None
            if len(memos) >= 2:
                yield _event("vc_consensus_started")
                consensus = await self._vc_consensus(memos)
                yield _event("vc_consensus_done", consensus=consensus)

            vc_data = {"memos": memos, "consensus": consensus}
            (run_dir / "vc-evaluation.json").write_text(json.dumps(vc_data, indent=2))
            (run_dir / "vc-evaluation.md").write_text(_render_vc_markdown(vc_data))
        except Exception as e:
            yield _event("vc_stage_error", message=str(e))

        yield _event(
            "final",
            n=final.n,
            score=final.premortem.score,
            verdict=final.premortem.verdict,
            green_lit=final.premortem.is_green_lit(),
            warning=warning,
            brd=final.brd,
            premortem={
                "score": final.premortem.score,
                "verdict": final.premortem.verdict,
                "summary": final.premortem.summary,
                "flags": [asdict(f) for f in final.premortem.flags],
            },
            run_id=run_id,
            total_iterations=len(iterations),
        )


def _fmt_usd(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n}"


def _render_vc_markdown(vc_data: dict) -> str:
    lines: list[str] = ["# VC Consideration Report", ""]
    consensus = vc_data.get("consensus")
    if consensus:
        lines.append("## Consensus")
        lines.append(f"- **Would-fund probability:** {consensus['would_fund_probability']}%")
        lines.append(
            f"- **Consensus valuation band (seed, post-money):** {_fmt_usd(consensus['consensus_valuation_low_usd'])}–{_fmt_usd(consensus['consensus_valuation_high_usd'])}"
        )
        lines.append(f"- **Typical check size:** {_fmt_usd(consensus['consensus_check_size_usd'])}")
        lines.append("")
        lines.append(f"**Biggest gating issue.** {consensus['biggest_gating_issue']}")
        lines.append("")
        lines.append(f"**Fundability.** {consensus['fundability_summary']}")
        lines.append("")
        lines.append("**Where VCs agree:**")
        for b in consensus.get("where_vcs_agree", []):
            lines.append(f"- {b}")
        lines.append("")
        lines.append("**Where VCs disagree:**")
        for b in consensus.get("where_vcs_disagree", []):
            lines.append(f"- {b}")
        lines.append("")

    for m in vc_data.get("memos", []):
        p = m["profile"]
        e = m["eval"]
        memo = e["memo"]
        lines.append(f"## {p['firm']} — {e['verdict'].upper()} (conviction {e['conviction']}/100)")
        lines.append(f"_{p['partner_voice']}_")
        lines.append("")
        lines.append(f"**Why matched.** {m['match_reason']}")
        lines.append("")
        lines.append(
            f"**Valuation.** {_fmt_usd(e['seed_valuation_low_usd'])}–{_fmt_usd(e['seed_valuation_high_usd'])} post-money. "
            f"Check size: {_fmt_usd(e['check_size_usd'])}. Would lead: {'yes' if e['would_lead'] else 'no'}."
        )
        lines.append(f"_{memo['valuation_rationale']}_")
        lines.append("")
        lines.append(f"**Thesis fit.** {memo['thesis_fit']}")
        lines.append("")
        lines.append("**What we like:**")
        for b in memo.get("what_we_like", []):
            lines.append(f"- {b}")
        lines.append("")
        lines.append("**What concerns us:**")
        for b in memo.get("what_concerns_us", []):
            lines.append(f"- {b}")
        lines.append("")
        lines.append(f"**Founder / team lens.** {memo['founder_team_lens']}")
        lines.append(f"**Market.** {memo['market_size_take']}")
        lines.append(f"**Moat.** {memo['moat_take']}")
        if memo.get("deal_breakers"):
            lines.append("")
            lines.append("**Deal breakers:**")
            for b in memo["deal_breakers"]:
                lines.append(f"- {b}")
        lines.append("")
    return "\n".join(lines)


def _premortem_to_dict(p: Premortem) -> dict:
    return {
        "score": p.score,
        "verdict": p.verdict,
        "summary": p.summary,
        "flags": [asdict(f) for f in p.flags],
    }
