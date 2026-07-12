"""Two-step idea distillation:

  1. strip_noise() — cheap, deterministic, regex-based cleanup of common PDF
     extraction junk (page numbers, repeated headers/footers, references,
     bare TOC lines, all-caps section markers).

  2. distill() — Haiku 4.5 turns the cleaned text into a structured brief
     (~1-2K chars) that downstream brainstorm/premortem stages can consume
     without re-paying tokens for the whole raw blob each iteration.

The user reviews and may edit the brief before running. Raw text is kept on
disk as a sidecar so nothing is lost.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Tuple

from anthropic import AsyncAnthropic

from .models_cfg import MODELS, Usage, usage_from_response


# ----------------------------------------------------------------------------
# STEP 1: strip_noise — deterministic cleanup
# ----------------------------------------------------------------------------

# Markers that frequently sit at the start of a "references / works cited /
# bibliography" section. Once we hit one, drop everything from that point on.
_REF_SECTION_HEADS = re.compile(
    r"^\s*(references|bibliography|works\s+cited|further\s+reading|citations)\s*:?\s*$",
    re.IGNORECASE,
)

# Bare page-number lines: "12", "Page 12", "12 / 30", "- 12 -".
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(page\s+)?\d{1,4}(\s*[/of]\s*\d{1,4})?\s*$",
    re.IGNORECASE,
)
_DASH_PAGE_NUMBER = re.compile(r"^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$")

# All-caps banner lines that pypdf often leaves over from PDF section headers.
_ALL_CAPS_BANNER = re.compile(r"^[A-Z0-9 \-:&,.()\[\]/]{8,}$")


def _is_pageish(line: str) -> bool:
    s = line.strip()
    return bool(_PAGE_NUMBER_LINE.match(s) or _DASH_PAGE_NUMBER.match(s))


def _find_repeated_header_footer(lines: list[str], min_repeats: int = 3) -> set[str]:
    """Lines that recur ≥ min_repeats times verbatim are almost certainly
    repeated page headers or footers. Identify and drop them.
    """
    counts: Counter[str] = Counter()
    for line in lines:
        s = line.strip()
        # Headers/footers are short. Body paragraphs typically aren't.
        if 4 <= len(s) <= 120:
            counts[s] += 1
    return {s for s, n in counts.items() if n >= min_repeats}


def strip_noise(text: str) -> Tuple[str, dict]:
    """Return (cleaned_text, stats). Pure function, no model calls."""
    raw = text or ""
    if not raw.strip():
        return "", {"raw_chars": 0, "cleaned_chars": 0, "removed_lines": 0, "reference_section_cut": False}

    # Normalize line endings.
    raw_lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    repeated = _find_repeated_header_footer(raw_lines)

    out: list[str] = []
    removed_lines = 0
    ref_cut = False
    for line in raw_lines:
        s = line.strip()
        if _REF_SECTION_HEADS.match(s):
            ref_cut = True
            removed_lines += 1
            break
        if not s:
            # Keep blank lines so paragraph breaks survive; collapsed later.
            out.append("")
            continue
        if _is_pageish(line):
            removed_lines += 1
            continue
        if s in repeated:
            removed_lines += 1
            continue
        # All-caps banners are usually noise UNLESS they're short headings the
        # author chose stylistically. We only drop banners ≥20 chars to be safe.
        if len(s) >= 20 and _ALL_CAPS_BANNER.match(s):
            removed_lines += 1
            continue
        out.append(line)

    # Collapse 3+ consecutive blank lines down to 2.
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

    return collapsed, {
        "raw_chars": len(raw),
        "cleaned_chars": len(collapsed),
        "removed_lines": removed_lines,
        "reference_section_cut": ref_cut,
        "repeated_lines_dropped": len(repeated),
    }


# ----------------------------------------------------------------------------
# STEP 2: distill — Haiku structured brief
# ----------------------------------------------------------------------------

DISTILL_SYSTEM = """You distill long business documents into a tight, structured brief that captures everything a downstream business-requirements-document (BRD) brainstorm and premortem evaluator would need.

Hard rules:
- The brief MUST be SHORTER than the input. If you cannot meaningfully reduce length, return the input verbatim. Never expand.
- Preserve every concrete claim that defines the idea: the problem, the customer, the model, the technology, the moat, the GTM, the differentiators, and any specific numbers (TAM, pricing, traction).
- Drop padding, restated points, generic-industry color, references to figures and tables, citations, and motivational filler.
- If the document is itself a BRD already, return a clean restatement, not a summary — keep the author's section headers.
- If the document is more like a research report or article, extract the implicit *idea* it implies (the business question the user seems to be asking about).
- If something material is ambiguous, surface it as a single line under "Open questions" rather than guessing. Don't pad these.
- Use minimal markdown. Section headers only when the source clearly had them or the content genuinely splits into 3+ sections. No bullet padding.

Return Markdown only — no preamble, no apology, no JSON. Start directly with the brief.
"""

DISTILL_USER = """Distill the document below.

---
{text}
---

Output the structured brief in Markdown now."""


async def distill(cleaned_text: str, client: AsyncAnthropic | None = None) -> Tuple[str, Usage]:
    """Call Haiku to produce a compact structured brief.

    Returns (brief_markdown, usage). Caller decides what to do with usage —
    we just return it so cost can be tracked in run.json.
    """
    if not cleaned_text.strip():
        return "", Usage(model=MODELS["distill"])

    c = client or AsyncAnthropic()
    model = MODELS["distill"]
    resp = await c.messages.create(
        model=model,
        max_tokens=1500,
        system=DISTILL_SYSTEM,
        messages=[{"role": "user", "content": DISTILL_USER.format(text=cleaned_text)}],
    )
    brief = resp.content[0].text.strip()
    usage = usage_from_response(model, resp)
    # Guard: if the model expanded the text, return the cleaned input instead.
    # We never want to make brainstorm input *longer* than it already was.
    if len(brief) >= len(cleaned_text):
        return cleaned_text, usage
    return brief, usage
