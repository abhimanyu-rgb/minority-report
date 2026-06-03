"""Bundle a completed run's artifacts into a single PDF report via WeasyPrint."""

from __future__ import annotations

import ctypes.util
import html
import json
import os
import sys
from pathlib import Path

import markdown as md


def _ensure_pango_loadable() -> None:
    """macOS SIP strips DYLD_* env vars from subprocesses, so `uvicorn` started
    without that env may not find Homebrew's Pango. Probe for the libs and add
    the brew lib dir to ctypes' search path explicitly before WeasyPrint imports.
    """
    if sys.platform != "darwin":
        return
    if ctypes.util.find_library("gobject-2.0") is not None:
        return
    for brew_lib in ("/opt/homebrew/lib", "/usr/local/lib"):
        candidate = Path(brew_lib) / "libgobject-2.0.0.dylib"
        if candidate.exists():
            existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            if brew_lib not in existing.split(":"):
                os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                    f"{brew_lib}:{existing}" if existing else brew_lib
                )
            try:
                ctypes.CDLL(str(candidate))
            except OSError:
                pass
            return


_ensure_pango_loadable()
from weasyprint import HTML, CSS  # noqa: E402


PDF_CSS = """
@page {
    size: A4;
    margin: 22mm 18mm 22mm 18mm;
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        color: #6b7280;
        font-size: 8.5pt;
        font-family: "Inter", "Helvetica", sans-serif;
    }
    @bottom-left {
        content: "Minority Report";
        color: #6b7280;
        font-size: 8.5pt;
        font-family: "Inter", "Helvetica", sans-serif;
    }
}
@page :first { @bottom-right { content: ""; } @bottom-left { content: ""; } }

body {
    font-family: "Inter", "Helvetica", "Arial", sans-serif;
    color: #1c2436;
    font-size: 10.5pt;
    line-height: 1.55;
}

/* Cover page */
.cover {
    page: cover;
    page-break-after: always;
}
@page cover {
    margin: 22mm 18mm 22mm 18mm;
    @bottom-right { content: ""; }
    @bottom-left { content: ""; }
}
.cover .brand {
    font-size: 11pt;
    letter-spacing: 0.32em;
    color: #2779e0;
    text-transform: uppercase;
    font-weight: 600;
    margin-bottom: 6mm;
}
.cover h1 {
    font-size: 30pt;
    font-weight: 700;
    margin: 0 0 4mm;
    color: #0f1f3a;
    letter-spacing: -0.01em;
    line-height: 1.15;
}
.cover .sub {
    font-size: 13pt;
    color: #4b5973;
    margin-bottom: 14mm;
    line-height: 1.45;
}
.cover-meta-row {
    display: table;
    width: 100%;
    margin-top: 12mm;
    padding-top: 10mm;
    border-top: 1px solid #cfd8e6;
}
.cover-meta-row .col {
    display: table-cell;
    width: 50%;
    vertical-align: top;
    padding-right: 8mm;
    padding-bottom: 6mm;
}
.cover-meta-row .label {
    font-size: 8.5pt;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    margin-bottom: 1mm;
    font-weight: 600;
}
.cover-meta-row .value {
    font-size: 14pt;
    color: #0f1f3a;
    font-weight: 600;
}
.cover .badge {
    display: inline-block;
    padding: 1.5mm 4mm;
    border-radius: 14pt;
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.cover .badge.green-lit { background: #d1fae5; color: #065f46; }
.cover .badge.warn      { background: #fef3c7; color: #78350f; }
.cover .fundability {
    margin-top: 12mm;
    padding: 6mm;
    background: #f3f6fb;
    border-left: 3pt solid #2779e0;
    border-radius: 2pt;
    font-size: 10pt;
    color: #28324b;
}
.cover .footer {
    margin-top: 14mm;
    border-top: 1px solid #cfd8e6;
    padding-top: 4mm;
    font-size: 8.5pt;
    color: #6b7280;
    display: table;
    width: 100%;
}
.cover .footer .left  { display: table-cell; text-align: left; }
.cover .footer .right { display: table-cell; text-align: right; }

/* Section blocks */
.section {
    page-break-before: always;
}
.section-label {
    font-size: 9pt;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    color: #2779e0;
    font-weight: 600;
    margin-bottom: 3mm;
}
.section > h1 {
    font-size: 22pt;
    font-weight: 700;
    color: #0f1f3a;
    margin: 0 0 6mm;
    padding-bottom: 4mm;
    border-bottom: 1.5pt solid #2779e0;
}

/* Markdown content */
.md h1 { font-size: 18pt; color: #0f1f3a; margin-top: 8mm; margin-bottom: 2mm; }
.md h2 { font-size: 14pt; color: #1c2b48; margin-top: 7mm; margin-bottom: 2mm; }
.md h3 { font-size: 12pt; color: #28324b; margin-top: 5mm; margin-bottom: 1.5mm; }
.md p  { margin: 0 0 3mm; }
.md ul, .md ol { margin: 0 0 4mm 5mm; padding: 0; }
.md li { margin-bottom: 1mm; }
.md strong { color: #0f1f3a; }
.md code {
    background: #eef2f7;
    padding: 0.3mm 1.4mm;
    border-radius: 1.5pt;
    font-family: "JetBrains Mono", "Menlo", monospace;
    font-size: 9pt;
    color: #1c2b48;
}
.md pre {
    background: #f3f6fb;
    padding: 3mm;
    border-radius: 2pt;
    font-size: 8.5pt;
    overflow-x: hidden;
    page-break-inside: avoid;
}
.md hr {
    border: 0;
    height: 1px;
    background: #cfd8e6;
    margin: 6mm 0;
}
.md blockquote {
    margin: 3mm 0;
    padding: 2mm 4mm;
    border-left: 2.5pt solid #2779e0;
    color: #28324b;
    background: #f8fafd;
}

/* VC consensus */
.vc-consensus-card {
    background: #f3f6fb;
    border: 1px solid #cfd8e6;
    border-radius: 3pt;
    padding: 6mm;
    margin-bottom: 6mm;
}
.vc-grid {
    display: table;
    width: 100%;
    margin-bottom: 5mm;
    border-spacing: 2.5mm 0;
}
.vc-grid .item {
    display: table-cell;
    width: 33.33%;
    background: #ffffff;
    padding: 4mm;
    border-radius: 2pt;
    border: 1px solid #dbe3ee;
    vertical-align: top;
}
.vc-grid .label {
    font-size: 8pt;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    margin-bottom: 1mm;
}
.vc-grid .big {
    font-size: 16pt;
    font-weight: 700;
    color: #0f1f3a;
}
.where-cols {
    display: table;
    width: 100%;
    border-spacing: 3mm 0;
    margin-top: 4mm;
}
.where-cols .col { display: table-cell; width: 50%; vertical-align: top; }
.where-cols h4 {
    font-size: 9pt; text-transform: uppercase; letter-spacing: 0.16em;
    color: #6b7280; margin: 0 0 2mm; font-weight: 600;
}
.where-cols ul { margin: 0; padding-left: 4mm; }
.where-cols li { font-size: 9.5pt; margin-bottom: 1mm; }

/* VC memo */
.vc-memo {
    border: 1px solid #cfd8e6;
    border-radius: 3pt;
    padding: 5mm;
    margin-bottom: 5mm;
}
.vc-memo-header {
    display: table;
    width: 100%;
    margin-bottom: 1.5mm;
}
.vc-memo-header .firm-cell    { display: table-cell; vertical-align: middle; }
.vc-memo-header .verdict-cell { display: table-cell; vertical-align: middle; text-align: right; }
.vc-memo h3 { margin: 0; font-size: 13pt; color: #0f1f3a; }
.verdict-pill {
    display: inline-block;
    padding: 1mm 3mm;
    border-radius: 2pt;
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}
.verdict-pill.invest      { background: #d1fae5; color: #065f46; }
.verdict-pill.lean-invest { background: #ecfdf5; color: #065f46; border: 1px solid #6ee7b7; }
.verdict-pill.pass        { background: #fee2e2; color: #991b1b; }
.verdict-pill.lean-pass   { background: #fef2f2; color: #991b1b; border: 1px solid #fca5a5; }
.vc-memo .voice { font-style: italic; color: #6b7280; font-size: 9pt; margin-bottom: 2.5mm; }
.vc-memo .valuation { font-weight: 700; color: #0f1f3a; margin-bottom: 1mm; font-size: 10.5pt; }
.vc-memo .rationale { font-style: italic; color: #4b5973; margin-bottom: 3mm; font-size: 9.5pt; }
.vc-memo .col-grid {
    display: table;
    width: 100%;
    border-spacing: 3mm 0;
    margin-top: 2mm;
}
.vc-memo .col { display: table-cell; width: 50%; vertical-align: top; }
.vc-memo .col h4 {
    font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.16em;
    color: #6b7280; margin: 0 0 1.5mm; font-weight: 600;
}
.vc-memo .col ul { margin: 0; padding-left: 4mm; }
.vc-memo .col li { font-size: 9.5pt; margin-bottom: 1mm; }
.vc-memo .meta-row {
    margin-top: 3mm; padding-top: 2.5mm; border-top: 1px solid #e5eaf2;
    font-size: 9.5pt; color: #4b5973;
}
.vc-memo .meta-row strong { color: #0f1f3a; }
.vc-memo .deal-breakers {
    margin-top: 3mm;
    padding: 2mm 3mm;
    background: #fef2f2;
    border-left: 2.5pt solid #ef4444;
    color: #991b1b;
    font-size: 9pt;
    border-radius: 1.5pt;
}
"""


def _md_to_html(text: str) -> str:
    return md.markdown(text or "", extensions=["extra", "sane_lists"])


def _fmt_usd(n: int | float | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    if n >= 1:
        return f"${n:.2f}"
    return f"${n:.4f}"


def _render_vc_html(vc_data: dict) -> str:
    if not vc_data:
        return '<p class="md">No VC consideration was produced for this run.</p>'

    parts: list[str] = []
    consensus = vc_data.get("consensus")
    if consensus:
        parts.append('<div class="vc-consensus-card">')
        parts.append('<div class="section-label">Consensus</div>')
        parts.append('<div class="vc-grid">')
        parts.append(
            f'<div class="item"><div class="label">Would-fund probability</div>'
            f'<div class="big">{consensus.get("would_fund_probability", 0)}%</div></div>'
        )
        parts.append(
            f'<div class="item"><div class="label">Seed valuation band</div>'
            f'<div class="big">{_fmt_usd(consensus.get("consensus_valuation_low_usd"))}'
            f'–{_fmt_usd(consensus.get("consensus_valuation_high_usd"))}</div></div>'
        )
        parts.append(
            f'<div class="item"><div class="label">Typical check size</div>'
            f'<div class="big">{_fmt_usd(consensus.get("consensus_check_size_usd"))}</div></div>'
        )
        parts.append('</div>')
        parts.append(
            f'<p><strong>Fundability.</strong> {html.escape(consensus.get("fundability_summary", ""))}</p>'
        )
        parts.append(
            f'<p><strong>Biggest gating issue.</strong> {html.escape(consensus.get("biggest_gating_issue", ""))}</p>'
        )
        agree = consensus.get("where_vcs_agree") or []
        disagree = consensus.get("where_vcs_disagree") or []
        parts.append('<div class="where-cols">')
        parts.append('<div class="col"><h4>Where VCs agree</h4><ul>')
        parts.extend(f'<li>{html.escape(b)}</li>' for b in agree)
        parts.append('</ul></div>')
        parts.append('<div class="col"><h4>Where VCs disagree</h4><ul>')
        parts.extend(f'<li>{html.escape(b)}</li>' for b in disagree)
        parts.append('</ul></div>')
        parts.append('</div>')
        parts.append('</div>')

    for m in vc_data.get("memos", []) or []:
        p = m.get("profile") or {}
        e = m.get("eval") or {}
        memo = e.get("memo") or {}
        verdict = (e.get("verdict") or "").strip()
        verdict_class = verdict.replace(" ", "-").lower() or "pass"
        deal_breakers = memo.get("deal_breakers") or []
        dealb_html = ""
        if deal_breakers:
            dealb_items = "; ".join(html.escape(b) for b in deal_breakers)
            dealb_html = f'<div class="deal-breakers"><strong>Deal breakers:</strong> {dealb_items}</div>'

        parts.append('<div class="vc-memo">')
        parts.append(
            f'<div class="vc-memo-header">'
            f'<div class="firm-cell"><h3>{html.escape(p.get("firm", "?"))}</h3></div>'
            f'<div class="verdict-cell"><span class="verdict-pill {verdict_class}">{html.escape(verdict.upper())} — conviction {e.get("conviction", 0)}/100</span></div>'
            f'</div>'
        )
        parts.append(f'<div class="voice">{html.escape(p.get("partner_voice", ""))}</div>')
        parts.append(
            f'<div class="valuation">{_fmt_usd(e.get("seed_valuation_low_usd"))}–'
            f'{_fmt_usd(e.get("seed_valuation_high_usd"))} post-money · '
            f'{_fmt_usd(e.get("check_size_usd"))} check · '
            f'{"would lead" if e.get("would_lead") else "would not lead"}</div>'
        )
        parts.append(f'<div class="rationale">{html.escape(memo.get("valuation_rationale", ""))}</div>')
        parts.append(f'<p><strong>Thesis fit.</strong> {html.escape(memo.get("thesis_fit", ""))}</p>')
        parts.append(f'<p><strong>Why matched.</strong> {html.escape(m.get("match_reason", ""))}</p>')

        likes = memo.get("what_we_like") or []
        concerns = memo.get("what_concerns_us") or []
        parts.append('<div class="col-grid">')
        parts.append('<div class="col"><h4>What we like</h4><ul>')
        parts.extend(f'<li>{html.escape(b)}</li>' for b in likes)
        parts.append('</ul></div>')
        parts.append('<div class="col"><h4>What concerns us</h4><ul>')
        parts.extend(f'<li>{html.escape(b)}</li>' for b in concerns)
        parts.append('</ul></div>')
        parts.append('</div>')

        parts.append('<div class="meta-row">')
        parts.append(f'<strong>Team lens.</strong> {html.escape(memo.get("founder_team_lens", ""))}<br/>')
        parts.append(f'<strong>Market.</strong> {html.escape(memo.get("market_size_take", ""))}<br/>')
        parts.append(f'<strong>Moat.</strong> {html.escape(memo.get("moat_take", ""))}')
        parts.append('</div>')
        parts.append(dealb_html)
        parts.append('</div>')

    return "\n".join(parts)


def render_run_pdf(run_dir: Path) -> bytes:
    """Bundle a completed run into a single PDF. Raises if required files are missing."""
    manifest = json.loads((run_dir / "run.json").read_text())
    final_brd = (run_dir / "final-brd.md").read_text()
    evolution_md = (run_dir / "evolution-report.md").read_text() if (run_dir / "evolution-report.md").is_file() else ""
    vc_data = {}
    vc_path = run_dir / "vc-evaluation.json"
    if vc_path.is_file():
        try:
            vc_data = json.loads(vc_path.read_text())
        except Exception:
            vc_data = {}

    idea_text = manifest.get("idea", "")
    final_score = manifest.get("final_score")
    green_lit = manifest.get("green_lit") or False
    total_iterations = manifest.get("total_iterations") or 0
    cost = (manifest.get("cost") or {}).get("total_usd")
    finished_at = manifest.get("finished_at", "")
    run_id = manifest.get("run_id", "")
    consensus = (vc_data or {}).get("consensus") or {}
    fundability = consensus.get("fundability_summary") or ""

    # Trim cover idea text to fit; full text is implicit in the BRD section anyway.
    idea_preview = idea_text.strip()
    if len(idea_preview) > 380:
        idea_preview = idea_preview[:377].rstrip() + "…"

    badge_class = "green-lit" if green_lit else "warn"
    badge_text = "Green-lit" if green_lit else "Best draft"

    cover_html = f"""
    <section class="cover">
      <div class="brand">Minority Report · Recursive BRD</div>
      <h1>{html.escape(_extract_title(final_brd) or "Final BRD")}</h1>
      <div class="sub">{html.escape(idea_preview)}</div>
      <div class="cover-meta-row">
        <div class="col">
          <div class="label">Status</div>
          <div class="value"><span class="badge {badge_class}">{badge_text}</span></div>
        </div>
        <div class="col">
          <div class="label">Future success score</div>
          <div class="value">{final_score if final_score is not None else "—"}/100</div>
        </div>
      </div>
      <div class="cover-meta-row" style="border-top:0; padding-top:0; margin-top:0;">
        <div class="col">
          <div class="label">Iterations</div>
          <div class="value">{total_iterations}</div>
        </div>
        <div class="col">
          <div class="label">Compute cost</div>
          <div class="value">{_fmt_usd(cost)}</div>
        </div>
      </div>
      {f'<div class="fundability"><strong>VC fundability take.</strong> {html.escape(fundability)}</div>' if fundability else ''}
      <div class="footer">
        <span class="left">Run {html.escape(run_id)}</span>
        <span class="right">{html.escape(finished_at)}</span>
      </div>
    </section>
    """

    brd_html = f"""
    <section class="section">
      <div class="section-label">Section 1</div>
      <h1>Final BRD</h1>
      <div class="md">{_md_to_html(final_brd)}</div>
    </section>
    """

    evolution_section = ""
    if evolution_md.strip():
        evolution_section = f"""
        <section class="section">
          <div class="section-label">Section 2</div>
          <h1>Evolution Report</h1>
          <div class="md">{_md_to_html(evolution_md)}</div>
        </section>
        """

    vc_section = f"""
    <section class="section">
      <div class="section-label">Section 3</div>
      <h1>VC Consideration</h1>
      {_render_vc_html(vc_data)}
    </section>
    """

    document = f"""<!doctype html>
    <html><head><meta charset="utf-8"><title>Minority Report</title></head>
    <body>{cover_html}{brd_html}{evolution_section}{vc_section}</body></html>"""

    return HTML(string=document).write_pdf(stylesheets=[CSS(string=PDF_CSS)])


def _extract_title(markdown_text: str) -> str:
    """Pull the first '# ' heading text from a BRD."""
    for line in (markdown_text or "").splitlines():
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return ""


_TITLE_MAX_LEN = 10


def extract_project_title(run_dir: Path) -> str:
    """Public helper: best-effort project name for filename / display.

    Truncates to the first 10 characters (word-aware when possible).
    Falls back through: BRD H1 -> first chars of idea -> empty string.
    """
    brd_path = run_dir / "final-brd.md"
    if brd_path.is_file():
        title = _extract_title(brd_path.read_text())
        if title:
            return _truncate(title, _TITLE_MAX_LEN)
    idea_path = run_dir / "idea.txt"
    if idea_path.is_file():
        idea = idea_path.read_text().strip()
        if idea:
            return _truncate(idea, _TITLE_MAX_LEN)
    return ""


def _truncate(s: str, n: int) -> str:
    """Trim to at most n chars; prefer word boundary if the trim falls inside a word."""
    s = s.strip()
    if len(s) <= n:
        return s
    head = s[:n]
    # If we cut mid-word and there's a space before n, back up to it.
    if " " in head and not s[n:n + 1].isspace():
        head = head.rsplit(" ", 1)[0]
    return head.strip() or s[:n]


def filename_slug(s: str, fallback: str = "report") -> str:
    """Sanitize a title into a safe filename slug.

    Keeps ASCII letters, digits, spaces, hyphens, underscores. Converts spaces
    to underscores. Collapses repeats. Lower-cases nothing — preserves the
    original casing so 'NuRecruit' stays 'NuRecruit'.
    """
    import re
    if not s:
        return fallback
    # Replace anything not [A-Za-z0-9 _-] with a space.
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", " ", s)
    # Collapse whitespace, swap spaces for underscores.
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    # Collapse runs of _ or -.
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned)
    cleaned = cleaned.strip("_-")
    return cleaned or fallback
