"""Post-loop multi-turn refinement chat on a completed BRD.

The recursive loop produces a final BRD. The user often wants to push further
without restarting: 'tighten the unit economics', 'add a competitive matrix',
'rewrite the GTM as a 90-day plan'. This module handles that conversation.

Persistence: each run gets a refinements.jsonl with one record per turn:
    {ts, role: "user"|"assistant", content, usage}

The full BRD is included as context in the system prompt every turn; the
running chat history is sent as messages. Sonnet handles this stage.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from anthropic import AsyncAnthropic

from .models_cfg import MODELS, usage_from_response

REFINE_MODEL_KEY = "refine"
# Default to Sonnet — same quality as brainstorm but no need for Opus here.
DEFAULT_REFINE_MODEL = "claude-sonnet-4-6"


def refine_model() -> str:
    return MODELS.get(REFINE_MODEL_KEY) or DEFAULT_REFINE_MODEL


REFINE_SYSTEM = """You are refining a Business Requirements Document (BRD) that has already been through a recursive brainstorm + premortem loop. Your job is to help the user iterate on specific sections, sharpen language, add missing analysis, or stress-test claims.

Rules:
- The user has the full BRD below as context. They will ask for specific edits or additions. Honor exactly what they ask for; do not redo the whole BRD unless asked.
- When you make changes, return the changed section(s) in clean Markdown with a short note up top saying *what* changed and *why* if the reasoning isn't obvious.
- If the user asks a question rather than for an edit, answer concisely and offer the next concrete step.
- Preserve numerical claims (TAM, pricing, traction) unless the user explicitly asks you to revise them.
- If the user asks for something that would weaken the BRD (e.g. removing a justified red flag from the premortem analysis), push back briefly and ask if they're sure.
- Keep responses tight. The user has already read a long BRD — don't pad.

The current final BRD is:

---
{brd}
---

The premortem score for this BRD is {score} with verdict "{verdict}". Summary: {summary}
"""


def _refine_dir(run_dir: Path) -> Path:
    d = run_dir / "refinements"
    d.mkdir(exist_ok=True)
    return d


def _history_path(run_dir: Path) -> Path:
    return _refine_dir(run_dir) / "thread.jsonl"


def load_history(run_dir: Path) -> list[dict]:
    p = _history_path(run_dir)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _append_turn(run_dir: Path, role: str, content: str, usage: dict | None = None) -> dict:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "content": content,
    }
    if usage is not None:
        record["usage"] = usage
    with _history_path(run_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


async def refine(run_dir: Path, user_message: str, client: AsyncAnthropic | None = None) -> dict:
    """Take one refinement turn. Returns the assistant turn record."""
    user_message = (user_message or "").strip()
    if not user_message:
        raise ValueError("Empty refinement message.")

    # Read the final BRD + premortem summary.
    brd_path = run_dir / "final-brd.md"
    pm_path = run_dir / "final-premortem.json"
    if not brd_path.is_file():
        raise FileNotFoundError("No final BRD on this run yet.")
    brd = brd_path.read_text()
    score = "—"
    verdict = "—"
    summary = ""
    if pm_path.is_file():
        try:
            pm = json.loads(pm_path.read_text())
            score = pm.get("score", "—")
            verdict = pm.get("verdict", "—")
            summary = (pm.get("summary") or "").strip()
        except Exception:
            pass

    history = load_history(run_dir)
    messages: list[dict] = []
    for turn in history:
        if turn["role"] in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    # Persist the user turn before the API call so we don't lose it on error.
    _append_turn(run_dir, "user", user_message)

    c = client or AsyncAnthropic()
    model = refine_model()
    resp = await c.messages.create(
        model=model,
        max_tokens=4000,
        system=REFINE_SYSTEM.format(brd=brd, score=score, verdict=verdict, summary=summary),
        messages=messages,
    )
    reply = resp.content[0].text
    usage = usage_from_response(model, resp)
    record = _append_turn(run_dir, "assistant", reply, usage.to_dict())
    return record
