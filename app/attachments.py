"""Server-side attachment store.

Each upload becomes an attachment: raw extract, heuristic-cleaned text, and
Haiku-distilled brief — all persisted to disk under a short-lived id. The
attachment is the file's *context*; the user's typed idea stays separate.
At /runs/create time, the two are composed.

Filesystem layout:
  attachments/<id>/
    raw.txt           # extracted text from PDF/DOCX/etc.
    cleaned.txt       # raw -> strip_noise()
    brief.md          # cleaned -> distill() via Haiku
    meta.json         # { id, filename, kind, pages, char_count, ...usage, created_at }
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "attachments"
BASE_DIR.mkdir(exist_ok=True)


def _new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def create(*, raw_text: str, cleaned_text: str, brief: str, filename: str, kind: str,
           pages: int | None, raw_chars: int, cleaned_chars: int, brief_chars: int,
           strip_stats: dict, usage: dict | None) -> dict:
    """Persist a new attachment. Returns its meta dict."""
    aid = _new_id()
    d = BASE_DIR / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.txt").write_text(raw_text)
    (d / "cleaned.txt").write_text(cleaned_text)
    (d / "brief.md").write_text(brief)
    meta = {
        "id": aid,
        "filename": filename,
        "kind": kind,
        "pages": pages,
        "raw_chars": raw_chars,
        "cleaned_chars": cleaned_chars,
        "brief_chars": brief_chars,
        "strip_stats": strip_stats,
        "distill_usage": usage or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load_meta(attachment_id: str) -> dict | None:
    p = BASE_DIR / attachment_id / "meta.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def load_brief(attachment_id: str) -> str | None:
    p = BASE_DIR / attachment_id / "brief.md"
    if not p.is_file():
        return None
    try:
        return p.read_text()
    except Exception:
        return None


def load_raw(attachment_id: str) -> str | None:
    p = BASE_DIR / attachment_id / "raw.txt"
    if not p.is_file():
        return None
    try:
        return p.read_text()
    except Exception:
        return None


def delete(attachment_id: str) -> bool:
    d = BASE_DIR / attachment_id
    if not d.is_dir():
        return False
    try:
        shutil.rmtree(d)
        return True
    except Exception:
        return False


def compose_idea(user_prompt: str, attachment_id: str | None) -> str:
    """Build the composite idea passed to the orchestrator.

    Rule (per product decision):
      - If user_prompt is non-empty: lead with user prompt, append attached
        context as a separate clearly-labeled section.
      - If user_prompt is empty: use the attachment's brief alone as the idea.
      - If no attachment: just return user_prompt.
    """
    user_prompt = (user_prompt or "").strip()
    if not attachment_id:
        return user_prompt
    brief = load_brief(attachment_id) or ""
    meta = load_meta(attachment_id) or {}
    if not brief.strip():
        return user_prompt
    fname = meta.get("filename") or "attached document"
    if not user_prompt:
        return brief
    return (
        f"{user_prompt}\n\n"
        f"---\n"
        f"## Attached context — from {fname}\n\n"
        f"The user attached the document below. Use it as ground truth for facts\n"
        f"about the idea. The user's prompt above is the lens through which to\n"
        f"evaluate it.\n\n"
        f"{brief}\n"
        f"---\n"
    )
