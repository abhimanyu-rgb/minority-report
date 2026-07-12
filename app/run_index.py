"""SQLite index over runs/ — fast list/search/filter without scanning JSON files.

Source of truth is still the filesystem. This is a derived cache, rebuilt
incrementally at the end of each run and on demand. Safe to delete and rebuild.

Schema:
  runs(
    run_id TEXT PRIMARY KEY,
    user_id TEXT,
    persona TEXT,
    sector TEXT,
    stage TEXT,
    theme TEXT,
    started_at TEXT,        -- ISO8601 UTC
    finished_at TEXT,
    status TEXT,            -- completed / aborted / errored
    final_score INTEGER,
    green_lit INTEGER,      -- 0/1
    total_iterations INTEGER,
    cost_usd REAL,
    title TEXT,             -- first H1 of final-brd.md
    idea_preview TEXT,      -- first 240 chars of idea
    outcome TEXT,           -- nullable
    outcome_note TEXT,
    outcome_updated_at TEXT
  )
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
INDEX_DIR = RUNS_DIR / "_index"
DB_PATH = INDEX_DIR / "runs.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  user_id TEXT,
  persona TEXT,
  sector TEXT,
  stage TEXT,
  theme TEXT,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  final_score INTEGER,
  green_lit INTEGER,
  total_iterations INTEGER,
  cost_usd REAL,
  title TEXT,
  idea_preview TEXT,
  outcome TEXT,
  outcome_note TEXT,
  outcome_updated_at TEXT,
  embedding_json TEXT,         -- JSON-encoded list[float] from Voyage; null if not yet embedded
  embedding_model TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_runs_sector ON runs(sector);
CREATE INDEX IF NOT EXISTS idx_runs_stage ON runs(stage);

-- Corpora are owner-scoped collections of memos / criteria / pitches.
-- Tier 1.4 (memo ingestion) + Tier 2.7 (two-sided) build on top of these.
-- One owner = one user_id for now; org grouping is a join layer added later.
CREATE TABLE IF NOT EXISTS corpora (
  corpus_id TEXT PRIMARY KEY,
  owner_user_id TEXT NOT NULL,
  kind TEXT NOT NULL,           -- 'vc_memo' | 'investment_criteria' | 'past_pitch' | 'other'
  label TEXT,                   -- human-readable name e.g. 'Sequoia India memos 2024'
  description TEXT,
  visibility TEXT DEFAULT 'private',  -- 'private' | 'shared_with' (future: list of user_ids)
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_corpora_owner ON corpora(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_corpora_kind ON corpora(kind);

CREATE TABLE IF NOT EXISTS corpus_items (
  item_id TEXT PRIMARY KEY,
  corpus_id TEXT NOT NULL,
  title TEXT,
  source_filename TEXT,
  content TEXT NOT NULL,        -- full text; we keep it for now since scale is small
  embedding_json TEXT,
  embedding_model TEXT,
  created_at TEXT,
  FOREIGN KEY (corpus_id) REFERENCES corpora(corpus_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_items_corpus ON corpus_items(corpus_id);
"""

OUTCOMES = {
    "unset",         # not yet set
    "advanced",      # moved to next stage / pursued
    "passed",        # decided not to pursue
    "invested",      # money in (investor)
    "declined",      # money out / killed
    "built",         # founder shipped it
    "pivoted",       # founder pivoted
    "killed",        # founder killed it
}


_MIGRATIONS_DONE = False


def _ensure_columns(c: sqlite3.Connection) -> None:
    """Add columns that may be missing from older index DBs. Idempotent."""
    existing = {row[1] for row in c.execute("PRAGMA table_info(runs)").fetchall()}
    for col, ddl in [
        ("embedding_json", "ALTER TABLE runs ADD COLUMN embedding_json TEXT"),
        ("embedding_model", "ALTER TABLE runs ADD COLUMN embedding_model TEXT"),
    ]:
        if col not in existing:
            c.execute(ddl)


@contextmanager
def _conn():
    global _MIGRATIONS_DONE
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        if not _MIGRATIONS_DONE:
            _ensure_columns(c)
            _MIGRATIONS_DONE = True
        yield c
        c.commit()
    finally:
        c.close()


def _extract_title(brd_path: Path) -> str:
    if not brd_path.is_file():
        return ""
    try:
        text = brd_path.read_text()
    except Exception:
        return ""
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()[:200]
    return ""


def _read_manifest(run_dir: Path) -> dict | None:
    p = run_dir / "run.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _row_from_manifest(m: dict, run_dir: Path) -> dict:
    attr = m.get("attribution") or {}
    title = _extract_title(run_dir / "final-brd.md")
    idea = (m.get("idea") or "").strip()[:240]
    # Outcome lives in a sidecar so it can be set independent of the run.
    outcome_path = run_dir / "outcome.json"
    outcome = "unset"
    outcome_note = ""
    outcome_ts = None
    if outcome_path.is_file():
        try:
            o = json.loads(outcome_path.read_text())
            outcome = o.get("outcome") or "unset"
            outcome_note = o.get("note") or ""
            outcome_ts = o.get("updated_at")
        except Exception:
            pass
    return {
        "run_id": m.get("run_id") or run_dir.name,
        "user_id": attr.get("user_id") or "anonymous",
        "persona": attr.get("persona") or "founder",
        "sector": attr.get("sector") or "other",
        "stage": attr.get("stage") or "unspecified",
        "theme": attr.get("theme") or "",
        "started_at": m.get("started_at"),
        "finished_at": m.get("finished_at"),
        "status": m.get("status"),
        "final_score": m.get("final_score"),
        "green_lit": 1 if m.get("green_lit") else 0,
        "total_iterations": m.get("total_iterations"),
        "cost_usd": float(((m.get("cost") or {}).get("total_usd")) or 0.0),
        "title": title,
        "idea_preview": idea,
        "outcome": outcome,
        "outcome_note": outcome_note,
        "outcome_updated_at": outcome_ts,
    }


UPSERT_SQL = """
INSERT INTO runs (run_id, user_id, persona, sector, stage, theme, started_at, finished_at, status,
                  final_score, green_lit, total_iterations, cost_usd, title, idea_preview,
                  outcome, outcome_note, outcome_updated_at)
VALUES (:run_id, :user_id, :persona, :sector, :stage, :theme, :started_at, :finished_at, :status,
        :final_score, :green_lit, :total_iterations, :cost_usd, :title, :idea_preview,
        :outcome, :outcome_note, :outcome_updated_at)
ON CONFLICT(run_id) DO UPDATE SET
  user_id=excluded.user_id,
  persona=excluded.persona,
  sector=excluded.sector,
  stage=excluded.stage,
  theme=excluded.theme,
  started_at=excluded.started_at,
  finished_at=excluded.finished_at,
  status=excluded.status,
  final_score=excluded.final_score,
  green_lit=excluded.green_lit,
  total_iterations=excluded.total_iterations,
  cost_usd=excluded.cost_usd,
  title=excluded.title,
  idea_preview=excluded.idea_preview,
  outcome=excluded.outcome,
  outcome_note=excluded.outcome_note,
  outcome_updated_at=excluded.outcome_updated_at
"""


def set_run_embedding(run_id: str, vector: list[float], model: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE runs SET embedding_json = ?, embedding_model = ? WHERE run_id = ?",
            (json.dumps(vector), model, run_id),
        )


def get_run_embedding(run_id: str) -> tuple[list[float] | None, str | None]:
    with _conn() as c:
        row = c.execute(
            "SELECT embedding_json, embedding_model FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None or not row["embedding_json"]:
        return None, None
    try:
        return json.loads(row["embedding_json"]), row["embedding_model"]
    except Exception:
        return None, None


def similar_runs(
    query_vec: list[float],
    *,
    viewer_user_id: str | None = None,
    same_user_only: bool = False,
    sector: str | None = None,
    stage: str | None = None,
    exclude_run_id: str | None = None,
    top_k: int = 5,
    min_cosine: float = 0.25,
) -> list[dict]:
    """Brute-force cosine over all embedded runs the viewer can see.

    Privacy rule (today, single-tenant): a user sees only their own runs
    unless explicit cross-tenant sharing is added later. `same_user_only=True`
    enforces this (the default for founder-facing 'peer runs' calls is to
    OPT OUT — only return matches owned by viewer_user_id). Cross-tenant peer
    matching will require careful anonymization later (Tier 2.6 work).
    """
    from .embeddings import cosine
    where = ["embedding_json IS NOT NULL", "status = 'completed'"]
    params: dict = {}
    if same_user_only and viewer_user_id:
        where.append("user_id = :viewer")
        params["viewer"] = viewer_user_id
    if sector:
        where.append("sector = :sector")
        params["sector"] = sector
    if stage:
        where.append("stage = :stage")
        params["stage"] = stage
    if exclude_run_id:
        where.append("run_id != :exclude")
        params["exclude"] = exclude_run_id
    sql = f"SELECT * FROM runs WHERE {' AND '.join(where)}"
    with _conn() as c:
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    scored = []
    for r in rows:
        try:
            v = json.loads(r["embedding_json"])
        except Exception:
            continue
        sim = cosine(query_vec, v)
        if sim >= min_cosine:
            r.pop("embedding_json", None)  # don't ship the vector back to clients
            r["similarity"] = round(sim, 4)
            scored.append(r)
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


# ----------------------------------------------------------------------------
# CORPORA — owner-scoped collections (memos, criteria, past pitches)
# ----------------------------------------------------------------------------

def create_corpus(*, owner_user_id: str, kind: str, label: str = "", description: str = "") -> str:
    import uuid
    from datetime import datetime, timezone
    cid = f"corp_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO corpora (corpus_id, owner_user_id, kind, label, description, visibility, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'private', ?, ?)""",
            (cid, owner_user_id, kind, label, description, now, now),
        )
    return cid


def list_corpora(owner_user_id: str) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM corpora WHERE owner_user_id = ? ORDER BY updated_at DESC",
            (owner_user_id,),
        ).fetchall()]


def get_corpus(corpus_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM corpora WHERE corpus_id = ?", (corpus_id,)).fetchone()
        return dict(row) if row else None


def delete_corpus(corpus_id: str, owner_user_id: str) -> bool:
    with _conn() as c:
        row = c.execute("SELECT owner_user_id FROM corpora WHERE corpus_id = ?", (corpus_id,)).fetchone()
        if not row or row["owner_user_id"] != owner_user_id:
            return False
        # ON DELETE CASCADE handles corpus_items
        c.execute("DELETE FROM corpora WHERE corpus_id = ?", (corpus_id,))
        return True


def add_corpus_item(*, corpus_id: str, title: str, content: str, source_filename: str = "",
                    embedding: list[float] | None = None, embedding_model: str | None = None) -> str:
    import uuid
    from datetime import datetime, timezone
    iid = f"item_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO corpus_items (item_id, corpus_id, title, source_filename, content,
                                          embedding_json, embedding_model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (iid, corpus_id, title, source_filename, content,
             json.dumps(embedding) if embedding else None, embedding_model, now),
        )
        c.execute("UPDATE corpora SET updated_at = ? WHERE corpus_id = ?", (now, corpus_id))
    return iid


def list_corpus_items(corpus_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT item_id, corpus_id, title, source_filename, created_at,
                      embedding_model, length(content) AS content_chars
               FROM corpus_items WHERE corpus_id = ? ORDER BY created_at DESC""",
            (corpus_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def similar_corpus_items(
    query_vec: list[float],
    *,
    corpus_id: str | None = None,
    owner_user_id: str | None = None,
    kind: str | None = None,
    top_k: int = 5,
    min_cosine: float = 0.25,
) -> list[dict]:
    """Find items semantically similar to query. Scope by corpus_id (one
    specific corpus), or by owner_user_id+kind (search all of a user's corpora
    of a kind, e.g. all of a VC's investment_criteria corpora)."""
    from .embeddings import cosine
    where = ["i.embedding_json IS NOT NULL"]
    params: dict = {}
    if corpus_id:
        where.append("i.corpus_id = :corpus_id")
        params["corpus_id"] = corpus_id
    if owner_user_id:
        where.append("c.owner_user_id = :owner")
        params["owner"] = owner_user_id
    if kind:
        where.append("c.kind = :kind")
        params["kind"] = kind
    sql = f"""
        SELECT i.item_id, i.corpus_id, i.title, i.source_filename, i.content, i.embedding_json, c.kind, c.label
        FROM corpus_items i JOIN corpora c ON c.corpus_id = i.corpus_id
        WHERE {' AND '.join(where)}
    """
    with _conn() as c:
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    out = []
    for r in rows:
        try:
            v = json.loads(r["embedding_json"])
        except Exception:
            continue
        sim = cosine(query_vec, v)
        if sim >= min_cosine:
            r.pop("embedding_json", None)
            r["similarity"] = round(sim, 4)
            out.append(r)
    out.sort(key=lambda x: x["similarity"], reverse=True)
    return out[:top_k]


def upsert_run(run_id: str) -> None:
    run_dir = RUNS_DIR / run_id
    m = _read_manifest(run_dir)
    if m is None:
        return
    row = _row_from_manifest(m, run_dir)
    with _conn() as c:
        c.execute(UPSERT_SQL, row)


def delete_run(run_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))


def rebuild_all() -> int:
    """Scan all run dirs and rebuild the index from scratch. Returns count."""
    n = 0
    with _conn() as c:
        c.execute("DELETE FROM runs")
        for d in RUNS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
                continue
            m = _read_manifest(d)
            if m is None:
                continue
            c.execute(UPSERT_SQL, _row_from_manifest(m, d))
            n += 1
    return n


def query_runs(
    *,
    user_id: str | None = None,
    sector: str | None = None,
    stage: str | None = None,
    persona: str | None = None,
    search: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    where = []
    params: dict = {}
    if user_id:
        where.append("user_id = :user_id")
        params["user_id"] = user_id
    if sector:
        where.append("sector = :sector")
        params["sector"] = sector
    if stage:
        where.append("stage = :stage")
        params["stage"] = stage
    if persona:
        where.append("persona = :persona")
        params["persona"] = persona
    if outcome:
        where.append("outcome = :outcome")
        params["outcome"] = outcome
    if search:
        where.append("(title LIKE :q OR idea_preview LIKE :q OR theme LIKE :q)")
        params["q"] = f"%{search}%"
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = max(1, min(200, int(limit)))
    params["offset"] = max(0, int(offset))
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def set_outcome(run_id: str, outcome: str, note: str = "") -> dict:
    from datetime import datetime, timezone
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome '{outcome}'. Valid: {sorted(OUTCOMES)}")
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "run.json").is_file():
        raise FileNotFoundError(f"Run {run_id} not found")
    payload = {
        "outcome": outcome,
        "note": (note or "").strip()[:1000],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "outcome.json").write_text(json.dumps(payload, indent=2))
    # Sync into the index.
    upsert_run(run_id)
    return payload
