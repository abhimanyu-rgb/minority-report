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
# Receives (iteration_number, top_issues, timeout_seconds). Returns the user's
# guidance text. Empty string == user skipped. Auto-skip on timeout returns "".
GuidanceFn = Callable[[int, list[dict], int], Awaitable[str]]

# Seconds to wait at strategic check-in before auto-continuing with no guidance.
GUIDANCE_TIMEOUT_S = int(os.getenv("GUIDANCE_TIMEOUT_S", "60"))

from .models_cfg import MODELS, Usage, usage_from_response

# Back-compat aliases (still referenced in some metadata writes).
BRAINSTORM_MODEL = MODELS["brainstorm"]
PREMORTEM_MODEL = MODELS["premortem"]
DEFAULT_MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "3"))
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
    iteration_id: str
    brd: str
    premortem: Premortem
    user_guidance_after: str = ""  # guidance the user provided AFTER this iteration's premortem
    brainstorm_started_at: str = ""
    brainstorm_finished_at: str = ""
    premortem_started_at: str = ""
    premortem_finished_at: str = ""
    brainstorm_model: str = ""
    premortem_model: str = ""
    user_guidance_used: str = ""  # guidance applied INTO this iteration's brainstorm (from previous round)
    usages: list[dict] = field(default_factory=list)  # per-call usage records (model + tokens + cost)
    cost_usd: float = 0.0


def _event(type_: str, **data) -> dict:
    return {"event": type_, "data": data}


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="microseconds") + "Z"


def _new_iteration_id(run_id: str, n: int) -> str:
    return f"{run_id}-i{n:02d}-{uuid.uuid4().hex[:6]}"


class RunLogger:
    """Append-only NDJSON event log for a run. Never rewrites."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "events.ndjson"
        # Open in append mode so we never overwrite prior events.
        self._fh = self.path.open("a", encoding="utf-8")

    def write(self, type_: str, data: dict) -> None:
        record = {"ts": _now_iso(), "type": type_, "data": data}
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of model output, tolerating fences and
    common emit defects. Tries (in order):

      1. Direct parse of the obvious {...} slice.
      2. Strip trailing commentary after the last balanced }.
      3. Common repair: drop trailing commas; replace smart quotes.

    Raises ValueError if all attempts fail.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in:\n{text[:500]}")
    candidate = text[start : end + 1]

    # Attempt 1: as-is
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Attempt 2: trailing-comma repair + smart-quote replacement
    repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
    repaired = repaired.replace("“", '"').replace("”", '"')
    repaired = repaired.replace("‘", "'").replace("’", "'")
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Attempt 3: balanced-brace walk to find the largest valid JSON prefix
    depth = 0
    last_valid = -1
    in_str = False
    esc = False
    for i, ch in enumerate(candidate):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_valid = i
    if last_valid > 0:
        try:
            return json.loads(candidate[: last_valid + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from:\n{candidate[:600]}")


# Anthropic SDK exceptions we treat as retryable.
RETRYABLE_API_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",  # base class for 5xx
    "RateLimitError",
    "InternalServerError",
    "ServiceUnavailableError",
}


async def _retry_api_call(coro_fn, *, max_attempts: int = 4, base_delay: float = 2.0):
    """Run an async API call with exponential backoff.

    `coro_fn` must be a zero-arg callable returning a fresh coroutine each call.
    Backoff: 2s, 4s, 8s. Honors Anthropic's Retry-After when present.
    """
    import inspect
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn()
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            retryable = name in RETRYABLE_API_ERROR_NAMES or (
                hasattr(e, "status_code") and getattr(e, "status_code", 0) in (408, 429, 500, 502, 503, 504, 529)
            )
            if not retryable or attempt == max_attempts:
                raise
            last_exc = e
            # Try to honor Retry-After header if present on the exception.
            retry_after = None
            resp = getattr(e, "response", None)
            if resp is not None and hasattr(resp, "headers"):
                ra = resp.headers.get("retry-after")
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        retry_after = None
            delay = retry_after if retry_after is not None else (base_delay * (2 ** (attempt - 1)))
            await asyncio.sleep(min(delay, 30.0))
    if last_exc:
        raise last_exc


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

    async def _messages_create(self, **kwargs):
        """All Anthropic calls go through here so they get retry + backoff."""
        async def _call():
            return await self.client.messages.create(**kwargs)
        return await _retry_api_call(_call)

    async def _brainstorm(self, user_msg: str) -> tuple[str, Usage]:
        model = MODELS["brainstorm"]
        resp = await self._messages_create(
            model=model,
            max_tokens=8000,
            system=BRAINSTORM_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text, usage_from_response(model, resp)

    async def _vc_match(self, brd: str, vc_db: list[dict]) -> tuple[list[dict], Usage]:
        model = MODELS["vc_match"]
        # Strip heavy fields the matcher does not need.
        compact = [
            {k: v for k, v in p.items() if k in ("id", "firm", "thesis", "what_they_fund", "sectors", "stage_focus")}
            for p in vc_db
        ]
        resp = await self._messages_create(
            model=model,
            max_tokens=1500,
            system=VC_MATCH_SYSTEM,
            messages=[{
                "role": "user",
                "content": VC_MATCH_USER.format(brd=brd, vc_db=json.dumps(compact, indent=2)),
            }],
        )
        data = _extract_json(resp.content[0].text)
        matches = data.get("matches", [])
        by_id = {p["id"]: p for p in vc_db}
        resolved = []
        for m in matches[:3]:
            profile = by_id.get(m.get("id"))
            if profile is None:
                continue
            resolved.append({"profile": profile, "reason": m.get("reason", "")})
        return resolved, usage_from_response(model, resp)

    async def _vc_eval(self, brd: str, profile: dict, final_score: int, final_summary: str,
                       corpus_exemplars: str = "") -> tuple[dict, Usage]:
        model = MODELS["vc_eval"]
        user_msg = VC_EVAL_USER.format(
            brd=brd, final_score=final_score, final_premortem_summary=final_summary
        )
        if corpus_exemplars.strip():
            user_msg = corpus_exemplars + "\n\n" + user_msg
        resp = await self._messages_create(
            model=model,
            max_tokens=3000,
            system=VC_EVAL_SYSTEM.format(profile=json.dumps(profile, indent=2)),
            messages=[{"role": "user", "content": user_msg}],
        )
        return _extract_json(resp.content[0].text), usage_from_response(model, resp)

    async def _vc_consensus(self, memos: list[dict]) -> tuple[dict, Usage]:
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
                "to_iron_out": m["eval"]["memo"].get("to_iron_out") or m["eval"]["memo"].get("what_concerns_us") or [],
                "deal_breakers": m["eval"]["memo"]["deal_breakers"],
                "valuation_rationale": m["eval"]["memo"]["valuation_rationale"],
            })
        model = MODELS["vc_consensus"]
        resp = await self._messages_create(
            model=model,
            max_tokens=1500,
            system=VC_CONSENSUS_SYSTEM,
            messages=[{
                "role": "user",
                "content": VC_CONSENSUS_USER.format(memos_block=json.dumps(compact, indent=2)),
            }],
        )
        return _extract_json(resp.content[0].text), usage_from_response(model, resp)

    async def _evolution_report(self, idea: str, iterations: list[Iteration], final: Iteration) -> tuple[str, Usage]:
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

        model = MODELS["evolution"]
        resp = await self._messages_create(
            model=model,
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
        return resp.content[0].text, usage_from_response(model, resp)

    async def _premortem(self, brd: str, weights_block: str = "", user_id: str | None = None) -> tuple[Premortem, Usage]:
        model = MODELS["premortem"]
        from .learning import get_premortem_priors_block
        from .calibration import calibration_block
        priors_block = get_premortem_priors_block()
        cal_block = calibration_block(user_id)
        # Append calibration to priors so the existing slot carries both.
        combined_priors = priors_block + ("\n" + cal_block if cal_block else "")
        resp = await self._messages_create(
            model=model,
            max_tokens=4000,
            system=PREMORTEM_SYSTEM,
            messages=[{"role": "user", "content": PREMORTEM_USER.format(brd=brd, priors_block=combined_priors, weights_block=weights_block)}],
        )
        raw = resp.content[0].text
        data = _extract_json(raw)
        flags = [Flag(**f) for f in data.get("flags", [])]
        premortem = Premortem(
            score=int(data["score"]),
            verdict=data.get("verdict", "needs-revision"),
            summary=data.get("summary", ""),
            flags=flags,
        )
        return premortem, usage_from_response(model, resp)

    async def run(
        self,
        idea: str,
        run_id: str,
        guidance_fn: GuidanceFn | None = None,
        max_iterations: int | None = None,
        vc_enabled: bool = True,
        attribution: dict | None = None,
    ) -> AsyncIterator[dict]:
        max_iter = max(1, min(20, int(max_iterations if max_iterations is not None else DEFAULT_MAX_ITERATIONS)))
        run_dir = RUNS_DIR / run_id

        # Resolve the user's tuned rubric weights (investor persona only).
        from .rubric import get_weights, render_weights_block
        attr = attribution or {}
        weights = get_weights(attr.get("user_id"))
        weights_block = render_weights_block(weights, attr.get("persona") or "founder")

        # Hard refusal to overwrite an existing run.
        if run_dir.exists() and any(run_dir.iterdir()):
            raise RuntimeError(f"Run directory {run_dir} already exists and is non-empty; refusing to overwrite.")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "iterations").mkdir(exist_ok=True)
        (run_dir / "idea.txt").write_text(idea)

        logger = RunLogger(run_dir)
        run_started_at = _now_iso()

        # Helper that emits to SSE AND appends to the immutable NDJSON log.
        def emit(type_: str, **data):
            logger.write(type_, data)
            return _event(type_, **data)

        def record_usage(role: str, usage: Usage, iteration_id: str | None = None) -> dict:
            """Add a usage record to run-level + iteration-level totals; return the dict."""
            d = usage.to_dict()
            d["role"] = role
            if iteration_id:
                d["iteration_id"] = iteration_id
            run_usages.append(d)
            return d

        # Shared state visible in `finally` for partial-manifest writes.
        iterations: list[Iteration] = []
        final: Iteration | None = None
        warning: str | None = None
        vc_data: dict | None = None
        status: str = "aborted"
        error_msg: str | None = None
        run_usages: list[dict] = []  # every call's usage record across the whole run

        try:
            yield emit(
                "run_started",
                run_id=run_id,
                max_iterations=max_iter,
                threshold=SCORE_THRESHOLD,
                brainstorm_model=BRAINSTORM_MODEL,
                premortem_model=PREMORTEM_MODEL,
                started_at=run_started_at,
            )

            previous_brd: str | None = None
            previous_premortem: Premortem | None = None
            pending_guidance: str = ""  # filled between iterations from user input

            for n in range(1, max_iter + 1):
                iteration_id = _new_iteration_id(run_id, n)
                iter_dir = run_dir / "iterations" / iteration_id
                if iter_dir.exists():
                    # Collision is essentially impossible (uuid4 6-hex) but be paranoid.
                    raise RuntimeError(f"Iteration directory {iter_dir} already exists; aborting to avoid overwrite.")
                iter_dir.mkdir(parents=True)

                yield emit("iteration_started", n=n, iteration_id=iteration_id)

                guidance_used = pending_guidance.strip()
                if previous_brd is None:
                    user_msg = BRAINSTORM_INITIAL_USER.format(idea=idea)
                else:
                    guidance_block = (
                        USER_GUIDANCE_BLOCK.format(guidance=guidance_used)
                        if guidance_used
                        else ""
                    )
                    user_msg = BRAINSTORM_REVISION_USER.format(
                        previous_brd=previous_brd,
                        premortem_summary=_format_premortem_for_revision(previous_premortem),
                        guidance_block=guidance_block,
                    )

                brainstorm_started_at = _now_iso()
                yield emit(
                    "brainstorm_started",
                    n=n,
                    iteration_id=iteration_id,
                    started_at=brainstorm_started_at,
                    model=MODELS["brainstorm"],
                )
                brd, brainstorm_usage = await self._brainstorm(user_msg)
                bu = record_usage("brainstorm", brainstorm_usage, iteration_id)
                brainstorm_finished_at = _now_iso()
                # Canonical iteration files (immutable).
                (iter_dir / "brd.md").write_text(brd)
                # Backward-compat flat path.
                (run_dir / f"brd-v{n}.md").write_text(brd)
                yield emit(
                    "brainstorm_done",
                    n=n,
                    iteration_id=iteration_id,
                    finished_at=brainstorm_finished_at,
                    brd=brd,
                    usage=bu,
                )

                premortem_started_at = _now_iso()
                yield emit(
                    "premortem_started",
                    n=n,
                    iteration_id=iteration_id,
                    started_at=premortem_started_at,
                    model=MODELS["premortem"],
                )
                premortem, premortem_usage = await self._premortem(brd, weights_block=weights_block, user_id=attr.get("user_id"))
                pu = record_usage("premortem", premortem_usage, iteration_id)
                premortem_finished_at = _now_iso()
                premortem_dict = _premortem_to_dict(premortem)
                (iter_dir / "premortem.json").write_text(json.dumps(premortem_dict, indent=2))
                (run_dir / f"premortem-v{n}.json").write_text(json.dumps(premortem_dict, indent=2))
                yield emit(
                    "premortem_done",
                    n=n,
                    iteration_id=iteration_id,
                    finished_at=premortem_finished_at,
                    score=premortem.score,
                    verdict=premortem.verdict,
                    summary=premortem.summary,
                    red_count=premortem.red_count,
                    yellow_count=premortem.yellow_count,
                    flags=[asdict(f) for f in premortem.flags],
                    usage=pu,
                )

                iter_usages = [bu, pu]
                iter_cost = round(sum(u["cost_usd"] for u in iter_usages), 6)
                run_total_cost = round(sum(u["cost_usd"] for u in run_usages), 6)
                yield emit(
                    "iteration_cost",
                    n=n,
                    iteration_id=iteration_id,
                    iteration_cost_usd=iter_cost,
                    run_cost_usd_so_far=run_total_cost,
                )

                iteration = Iteration(
                    n=n,
                    iteration_id=iteration_id,
                    brd=brd,
                    premortem=premortem,
                    brainstorm_started_at=brainstorm_started_at,
                    brainstorm_finished_at=brainstorm_finished_at,
                    premortem_started_at=premortem_started_at,
                    premortem_finished_at=premortem_finished_at,
                    brainstorm_model=MODELS["brainstorm"],
                    premortem_model=MODELS["premortem"],
                    user_guidance_used=guidance_used,
                    usages=iter_usages,
                    cost_usd=iter_cost,
                )
                iterations.append(iteration)
                previous_brd = brd
                previous_premortem = premortem

                # Write iteration sidecar now (without trailing guidance — written again after pause).
                _write_iter_sidecar(iter_dir, iteration, run_id, premortem_dict)

                if premortem.is_green_lit():
                    yield emit("green_lit", n=n, iteration_id=iteration_id, score=premortem.score)
                    break

                if n == max_iter:
                    yield emit("cap_hit", n=n, iteration_id=iteration_id)
                    break

                # Strategic-pause: surface top issues, wait for user guidance (or skip / timeout).
                top_issues = [asdict(f) for f in _top_strategic_issues(premortem, k=5)]
                yield emit(
                    "awaiting_input",
                    n=n,
                    iteration_id=iteration_id,
                    next_iteration=n + 1,
                    top_issues=top_issues,
                    score=premortem.score,
                    timeout_s=GUIDANCE_TIMEOUT_S,
                )
                if guidance_fn is not None:
                    pending_guidance = await guidance_fn(n, top_issues, GUIDANCE_TIMEOUT_S)
                else:
                    pending_guidance = ""
                iteration.user_guidance_after = pending_guidance.strip()
                if pending_guidance.strip():
                    (iter_dir / "guidance.txt").write_text(pending_guidance)
                    # Backward-compat flat path.
                    (run_dir / f"guidance-after-v{n}.txt").write_text(pending_guidance)
                    # Tier 1.3 — record per-user calibration signal from this
                    # guidance turn vs the flags they just saw. Best-effort.
                    try:
                        from .calibration import record_interaction
                        from .learning import _norm_key as _nk
                        uid = (attr.get("user_id") or "").strip()
                        if uid and uid != "anonymous":
                            for f in top_issues:
                                key = _nk(f.get("section", ""), f.get("title", ""))
                                record_interaction(uid, key, pending_guidance)
                    except Exception:
                        pass
                    yield emit(
                        "guidance_received",
                        n=n,
                        iteration_id=iteration_id,
                        guidance=pending_guidance,
                    )
                else:
                    yield emit("guidance_skipped", n=n, iteration_id=iteration_id)
                # Rewrite sidecar so the guidance-after field is captured.
                _write_iter_sidecar(iter_dir, iteration, run_id, premortem_dict)

            # Pick final.
            #   - If the last iteration is green-lit, take it.
            #   - Otherwise take the highest-scoring iteration; on a score tie,
            #     prefer the LATER iteration (more rounds of guidance/feedback
            #     have been folded in, so the later draft is the more refined
            #     one). max() returns the first match on ties, so we walk
            #     iterations in reverse to bias toward latest-on-tie.
            if iterations[-1].premortem.is_green_lit():
                final = iterations[-1]
                warning = None
            else:
                final = max(reversed(iterations), key=lambda it: it.premortem.score)
                warning = (
                    f"Did not meet the bar (score ≥ {SCORE_THRESHOLD} and zero red flags) "
                    f"after {len(iterations)} iterations. Publishing the best-scoring draft "
                    f"(iteration {final.n}, score {final.premortem.score}). "
                    f"Remaining red flags: {final.premortem.red_count}."
                )

            (run_dir / "final-brd.md").write_text(final.brd)
            (run_dir / "final-premortem.json").write_text(json.dumps(_premortem_to_dict(final.premortem), indent=2))

            yield emit("evolution_report_started", model=MODELS["evolution"])
            evo_usage_dict: dict | None = None
            try:
                evolution_report, evo_usage = await self._evolution_report(idea, iterations, final)
                evo_usage_dict = record_usage("evolution", evo_usage)
            except Exception as e:
                evolution_report = f"# Evolution Report\n\nFailed to generate: {e}"
            (run_dir / "evolution-report.md").write_text(evolution_report)
            yield emit("evolution_report_done", report=evolution_report, usage=evo_usage_dict)

            # VC consideration stage: match top 3 firms, run partner memos in parallel, synthesize consensus.
            if not vc_enabled:
                yield emit("vc_skipped", reason="User disabled VC consideration for this run.")
            else:
                try:
                    yield emit("vc_stage_started")
                    vc_db = json.loads(VC_PROFILES_PATH.read_text())
                    yield emit("vc_matching", model=MODELS["vc_match"])
                    matched, match_usage = await self._vc_match(final.brd, vc_db)
                    record_usage("vc_match", match_usage)
                    yield emit(
                        "vc_matched",
                        matches=[{"firm": m["profile"]["firm"], "id": m["profile"]["id"], "reason": m["reason"]} for m in matched],
                        usage=match_usage.to_dict(),
                    )

                    # Tier 1.4 — if the requesting user owns a vc_memo / past_pitch
                    # corpus, fetch top-3 semantically similar items relative to
                    # this BRD and inject as exemplars so the VC eval reflects
                    # the firm's actual voice / criteria.
                    exemplars_block = ""
                    try:
                        from .embeddings import is_available, embed
                        from .run_index import similar_corpus_items
                        uid = (attr.get("user_id") or "").strip()
                        if is_available() and uid and uid != "anonymous":
                            q = await embed(final.brd, input_type="query")
                            ex_items = similar_corpus_items(
                                q["vector"], owner_user_id=uid, kind="vc_memo", top_k=3, min_cosine=0.3
                            )
                            if not ex_items:
                                ex_items = similar_corpus_items(
                                    q["vector"], owner_user_id=uid, kind="investment_criteria",
                                    top_k=3, min_cosine=0.3,
                                )
                            if ex_items:
                                parts = ["## Your firm's exemplar memos / criteria",
                                         "Reference these in tone and rubric. Treat them as ground truth for *how your firm evaluates*."]
                                for ex in ex_items:
                                    parts.append(f"\n### {ex.get('label') or ex.get('title')} (sim {ex['similarity']})")
                                    parts.append(ex.get("content", "")[:2000])
                                exemplars_block = "\n".join(parts)
                    except Exception:
                        exemplars_block = ""

                    yield emit("vc_evaluating", count=len(matched), model=MODELS["vc_eval"])
                    evals = await asyncio.gather(
                        *[self._vc_eval(final.brd, m["profile"], final.premortem.score, final.premortem.summary, corpus_exemplars=exemplars_block) for m in matched],
                        return_exceptions=True,
                    )
                    memos: list[dict] = []
                    for m, e in zip(matched, evals):
                        if isinstance(e, Exception):
                            yield emit("vc_eval_error", firm=m["profile"]["firm"], message=str(e))
                            continue
                        eval_payload, eval_usage = e
                        eu = record_usage("vc_eval", eval_usage)
                        memos.append({"profile": m["profile"], "match_reason": m["reason"], "eval": eval_payload})
                        yield emit(
                            "vc_eval_done",
                            firm=m["profile"]["firm"],
                            eval=eval_payload,
                            match_reason=m["reason"],
                            profile=m["profile"],
                            usage=eu,
                        )

                    consensus = None
                    if len(memos) >= 2:
                        yield emit("vc_consensus_started", model=MODELS["vc_consensus"])
                        consensus, consensus_usage = await self._vc_consensus(memos)
                        cu = record_usage("vc_consensus", consensus_usage)
                        yield emit("vc_consensus_done", consensus=consensus, usage=cu)

                    vc_data = {"memos": memos, "consensus": consensus}
                    (run_dir / "vc-evaluation.json").write_text(json.dumps(vc_data, indent=2))
                    (run_dir / "vc-evaluation.md").write_text(_render_vc_markdown(vc_data))
                except Exception as e:
                    yield emit("vc_stage_error", message=str(e))

            status = "completed"

            total_cost = round(sum(u["cost_usd"] for u in run_usages), 6)
            yield emit(
                "final",
                n=final.n,
                iteration_id=final.iteration_id,
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
                cost_usd=total_cost,
            )
        except Exception as exc:
            status = "errored"
            error_msg = f"{type(exc).__name__}: {exc}"
            try:
                logger.write("run_errored", {"error": error_msg})
            except Exception:
                pass
            raise
        finally:
            # Always write a manifest with whatever state we have.
            try:
                _write_run_manifest(
                    run_dir=run_dir,
                    run_id=run_id,
                    idea=idea,
                    started_at=run_started_at,
                    finished_at=_now_iso(),
                    max_iter=max_iter,
                    threshold=SCORE_THRESHOLD,
                    iterations=iterations,
                    final=final,
                    warning=warning,
                    vc_data=vc_data,
                    status=status,
                    error=error_msg,
                    run_usages=run_usages,
                    vc_enabled=vc_enabled,
                    attribution=attribution or {"user_id": "anonymous", "persona": "founder"},
                )
            except Exception:
                pass
            logger.close()
            # Rebuild the cross-run flag-pattern index so the next premortem
            # picks up this run's signal. Best-effort; never blocks the run.
            try:
                from .learning import rebuild_flag_patterns
                rebuild_flag_patterns()
            except Exception:
                pass
            # Sync into the SQLite runs index for fast list/search.
            try:
                from .run_index import upsert_run, set_run_embedding
                upsert_run(run_id)
            except Exception:
                pass
            # Best-effort: embed the final BRD so this run participates in
            # similarity search for future peer-run / corpora matching.
            # Failures here NEVER block the run from completing.
            try:
                from .embeddings import is_available, embed
                from pathlib import Path as _P
                brd_path = run_dir / "final-brd.md"
                if is_available() and brd_path.is_file() and status == "completed":
                    text = brd_path.read_text()
                    result = await embed(text, input_type="document")
                    set_run_embedding(run_id, result["vector"], result["model"])
            except Exception:
                # Quietly skip; logs would be nice eventually.
                pass


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
        lines.append("**To iron out:**")
        for b in (memo.get("to_iron_out") or memo.get("what_concerns_us") or []):
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


def _write_iter_sidecar(iter_dir: Path, it: Iteration, run_id: str, premortem_dict: dict) -> None:
    """Write the iter.json metadata sidecar for an iteration. Idempotent."""
    sidecar = {
        "iteration_id": it.iteration_id,
        "run_id": run_id,
        "n": it.n,
        "brainstorm_model": it.brainstorm_model,
        "premortem_model": it.premortem_model,
        "brainstorm_started_at": it.brainstorm_started_at,
        "brainstorm_finished_at": it.brainstorm_finished_at,
        "premortem_started_at": it.premortem_started_at,
        "premortem_finished_at": it.premortem_finished_at,
        "premortem": premortem_dict,
        "user_guidance_used": it.user_guidance_used,
        "user_guidance_after": it.user_guidance_after,
        "is_green_lit": it.premortem.is_green_lit(),
        "cost_usd": it.cost_usd,
        "usages": it.usages,
    }
    (iter_dir / "iter.json").write_text(json.dumps(sidecar, indent=2))


def _write_run_manifest(
    *,
    run_dir: Path,
    run_id: str,
    idea: str,
    started_at: str,
    finished_at: str,
    max_iter: int,
    threshold: int,
    iterations: list[Iteration],
    final: Iteration | None,
    warning: str | None,
    vc_data: dict | None,
    status: str,  # "completed" | "aborted" | "errored"
    error: str | None = None,
    run_usages: list[dict] | None = None,
    vc_enabled: bool = True,
    attribution: dict | None = None,
) -> None:
    """Write run.json — the top-level manifest. Resilient: works with partial state.

    Always overwrites in place; the file holds the latest snapshot of run state.
    Per-iteration files in iterations/ are append-only and never touched here.
    """
    run_usages = run_usages or []
    cost_usd = round(sum(u["cost_usd"] for u in run_usages), 6)
    # Aggregate per-role + per-model for quick reading.
    cost_by_role: dict[str, float] = {}
    cost_by_model: dict[str, float] = {}
    tokens_in = 0
    tokens_out = 0
    for u in run_usages:
        cost_by_role[u["role"]] = round(cost_by_role.get(u["role"], 0.0) + u["cost_usd"], 6)
        cost_by_model[u["model"]] = round(cost_by_model.get(u["model"], 0.0) + u["cost_usd"], 6)
        tokens_in += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        tokens_out += u.get("output_tokens", 0)

    manifest = {
        "run_id": run_id,
        "schema_version": 3,
        "status": status,
        "attribution": attribution or {"user_id": "anonymous", "persona": "founder"},
        "started_at": started_at,
        "finished_at": finished_at,
        "settings": {
            "max_iterations": max_iter,
            "score_threshold": threshold,
            "vc_enabled": vc_enabled,
            "models": dict(MODELS),
        },
        "idea": idea,
        "total_iterations": len(iterations),
        "warning": warning,
        "error": error,
        "cost": {
            "total_usd": cost_usd,
            "by_role": cost_by_role,
            "by_model": cost_by_model,
            "tokens_input_total": tokens_in,
            "tokens_output_total": tokens_out,
        },
        "usages": run_usages,
        "iterations": [
            {
                "iteration_id": it.iteration_id,
                "n": it.n,
                "score": it.premortem.score,
                "verdict": it.premortem.verdict,
                "red_count": it.premortem.red_count,
                "yellow_count": it.premortem.yellow_count,
                "had_guidance_in": bool(it.user_guidance_used),
                "had_guidance_after": bool(it.user_guidance_after),
                "brainstorm_started_at": it.brainstorm_started_at,
                "brainstorm_finished_at": it.brainstorm_finished_at,
                "premortem_started_at": it.premortem_started_at,
                "premortem_finished_at": it.premortem_finished_at,
                "cost_usd": it.cost_usd,
            }
            for it in iterations
        ],
        "final_iteration_id": final.iteration_id if final else None,
        "final_iteration_n": final.n if final else None,
        "final_score": final.premortem.score if final else None,
        "final_verdict": final.premortem.verdict if final else None,
        "green_lit": final.premortem.is_green_lit() if final else None,
        "vc": (
            {
                "matched_firms": [m["profile"]["firm"] for m in (vc_data.get("memos") or [])],
                "consensus": vc_data.get("consensus"),
            }
            if vc_data
            else None
        ),
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))


def _premortem_to_dict(p: Premortem) -> dict:
    return {
        "score": p.score,
        "verdict": p.verdict,
        "summary": p.summary,
        "flags": [asdict(f) for f in p.flags],
    }
