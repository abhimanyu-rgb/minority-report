"""FastAPI app: idea form + SSE stream of the brainstorm/premortem loop with strategic-pause."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

load_dotenv()

from .orchestrator import Orchestrator  # noqa: E402
from .report_pdf import render_run_pdf, extract_project_title, filename_slug  # noqa: E402
from .extract import extract as extract_text, ExtractError, MAX_BYTES  # noqa: E402
from .distill import strip_noise, distill  # noqa: E402
from .models_cfg import MODELS  # noqa: E402
from .learning import compute_analytics, rebuild_flag_patterns, load_flag_patterns  # noqa: E402
from .personas import PERSONAS, normalize_persona, is_admin, SECTORS, STAGES, normalize_sector, normalize_stage  # noqa: E402

from fastapi.responses import Response  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Minority Report")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Per-run guidance queues. The orchestrator awaits a put; the resume endpoint
# puts the user's text. A None value means "skip" (treated as empty string).
GUIDANCE_QUEUES: dict[str, asyncio.Queue[str]] = {}

# Per-run live event broadcast: a list of subscriber queues. The orchestrator
# task pushes each emitted event onto every subscriber's queue. The SSE
# endpoint creates one subscriber per HTTP connection. This decouples the
# orchestrator's lifecycle from any single client connection — if a browser
# disconnects mid-run, the orchestrator keeps running and the next connection
# to /stream/<run_id> replays the on-disk events.ndjson and then subscribes
# to live events.
LIVE_RUNS: dict[str, dict] = {}
# Each LIVE_RUNS[run_id] = {
#   "task": asyncio.Task,
#   "subscribers": list[asyncio.Queue],
#   "done": bool,
#   "started_at": str,
# }

SSE_PING_S = 5  # heartbeat interval — keeps idle-looking connections alive


def cleanup_incomplete_runs() -> dict:
    """Delete any run directory whose run.json shows the run never completed.

    Criteria for "incomplete":
      - run.json missing (run crashed before manifest written)
      - run.json.status != 'completed'
      - final-brd.md missing
    Each deletion also clears the run from the SQLite index.
    """
    import shutil
    if not RUNS_DIR.exists():
        return {"deleted": [], "kept": 0}
    deleted: list[str] = []
    kept = 0
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        if run_dir.name.startswith("_") or run_dir.name.startswith("."):
            continue
        is_complete = False
        manifest_path = run_dir / "run.json"
        if manifest_path.is_file() and (run_dir / "final-brd.md").is_file():
            try:
                m = json.loads(manifest_path.read_text())
                if m.get("status") == "completed":
                    is_complete = True
            except Exception:
                pass
        if is_complete:
            kept += 1
            continue
        try:
            shutil.rmtree(run_dir)
            deleted.append(run_dir.name)
            try:
                from .run_index import delete_run as delete_run_index
                delete_run_index(run_dir.name)
            except Exception:
                pass
        except Exception:
            pass
    return {"deleted": deleted, "kept": kept}


@app.on_event("startup")
async def _on_startup():
    """Clean any partial runs left behind by a previous crash / restart."""
    try:
        result = cleanup_incomplete_runs()
        if result["deleted"]:
            print(f"[startup] cleaned {len(result['deleted'])} incomplete run(s): {result['deleted']}")
    except Exception as e:
        print(f"[startup] cleanup failed: {e}")


def _asset_version() -> str:
    """Latest mtime across static assets, used as a cache-buster query string.

    Without this, browsers cache /static/app.js indefinitely and users keep
    running stale JS after a deploy — which silently breaks features that
    changed the upload/run response shape.
    """
    try:
        static = BASE_DIR / "static"
        mtimes = [p.stat().st_mtime for p in static.iterdir() if p.is_file()]
        if not mtimes:
            return "1"
        return str(int(max(mtimes)))
    except Exception:
        return "1"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"asset_version": _asset_version()})


async def _run_orchestrator(idea: str, run_id: str, max_iterations: int, vc_enabled: bool, attribution: dict) -> None:
    """Background task: runs the orchestrator, pushes each event to all subscribers."""
    run_state = LIVE_RUNS[run_id]
    guidance_queue: asyncio.Queue[str] = GUIDANCE_QUEUES[run_id]

    async def guidance_fn(iteration: int, top_issues: list[dict], timeout_s: int) -> str:
        """Wait for user guidance, but slide the deadline forward on heartbeats.

        Behaviour:
          - No interaction at all -> times out after `timeout_s` seconds, returns "".
          - User starts typing (client POSTs /heartbeat) -> the deadline becomes
            "no auto-skip while typing": each heartbeat sets last_heartbeat_at.
            We never auto-skip once a heartbeat has been received; only an
            explicit POST /resume (Continue or Skip) advances the loop.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        # Clear any stale heartbeat from the previous iteration's pause.
        LIVE_RUNS[run_id]["last_heartbeat_at"] = None

        while True:
            # Race the queue against a 1-second tick so we can re-check the
            # deadline / heartbeat state each second.
            try:
                return await asyncio.wait_for(guidance_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

            # If the client has ever heartbeat for this iteration, the user is
            # engaged — wait indefinitely for an explicit Continue/Skip.
            if LIVE_RUNS[run_id].get("last_heartbeat_at") is not None:
                continue

            # No heartbeat yet — honor the initial timeout.
            if loop.time() >= deadline:
                return ""

    orch = Orchestrator()
    try:
        async for ev in orch.run(idea, run_id=run_id, guidance_fn=guidance_fn, max_iterations=max_iterations, vc_enabled=vc_enabled, attribution=attribution):
            for subq in list(run_state["subscribers"]):
                try:
                    subq.put_nowait(ev)
                except Exception:
                    pass
    except Exception as e:
        ev = {"event": "error", "data": {"message": str(e)}}
        for subq in list(run_state["subscribers"]):
            try:
                subq.put_nowait(ev)
            except Exception:
                pass
    finally:
        run_state["done"] = True
        # Send a sentinel so any subscribed SSE generators can close cleanly.
        sentinel = {"event": "__END__", "data": {}}
        for subq in list(run_state["subscribers"]):
            try:
                subq.put_nowait(sentinel)
            except Exception:
                pass
        GUIDANCE_QUEUES.pop(run_id, None)


def _start_run(idea: str, max_iterations: int, vc_enabled, user_id: str, persona: str, sector: str, stage: str, theme: str) -> str:
    """Allocate a run_id, register in LIVE_RUNS, kick off the orchestrator task.

    Returns the run_id. The caller is responsible for attaching an SSE stream
    via /stream/<run_id>.
    """
    max_iterations = max(1, min(20, int(max_iterations)))
    vc_on = str(vc_enabled).lower() not in ("0", "false", "no", "off", "")
    attribution = {
        "user_id": (user_id or "").strip()[:120] or "anonymous",
        "persona": normalize_persona(persona),
        "sector": normalize_sector(sector),
        "stage": normalize_stage(stage),
        "theme": (theme or "").strip()[:200],
    }
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]

    GUIDANCE_QUEUES[run_id] = asyncio.Queue()
    LIVE_RUNS[run_id] = {
        "task": None,
        "subscribers": [],
        "done": False,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "last_heartbeat_at": None,
    }
    LIVE_RUNS[run_id]["task"] = asyncio.create_task(
        _run_orchestrator(idea, run_id, max_iterations, vc_on, attribution)
    )
    return run_id


@app.post("/runs/create")
async def create_run(request: Request):
    """Kick off a run from a JSON body. Composes the user's prompt with any
    attached file's distilled brief into the idea passed to the orchestrator.

    Body fields:
      idea (optional)        — user's typed prompt. May be empty if attachment present.
      attachment_id (optional)— id from /upload. Its brief is composed into the idea.
      user_id, persona, sector, stage, theme, max_iterations, vc_enabled — as before.

    Returns {run_id}. Open EventSource('/stream/<run_id>') next.
    """
    from . import attachments as _att

    body = await request.json()
    user_prompt = (body.get("idea") or "").strip()
    attachment_id = (body.get("attachment_id") or "").strip() or None

    if not user_prompt and not attachment_id:
        raise HTTPException(status_code=400, detail="Empty idea — type something or attach a file.")

    # Validate attachment exists before we burn a run_id.
    att_meta = None
    if attachment_id:
        att_meta = _att.load_meta(attachment_id)
        if att_meta is None:
            raise HTTPException(status_code=404, detail=f"Attachment {attachment_id} not found.")

    composite_idea = _att.compose_idea(user_prompt, attachment_id)
    if not composite_idea.strip():
        raise HTTPException(status_code=400, detail="Composed idea is empty.")

    run_id = _start_run(
        idea=composite_idea,
        max_iterations=body.get("max_iterations", 5),
        vc_enabled=body.get("vc_enabled", "1"),
        user_id=body.get("user_id", ""),
        persona=body.get("persona", ""),
        sector=body.get("sector", ""),
        stage=body.get("stage", ""),
        theme=body.get("theme", ""),
    )

    # Persist attachment artifacts as run sidecars so the run is fully
    # reproducible even if the attachment is later deleted. Best-effort.
    if attachment_id:
        try:
            run_dir = RUNS_DIR / run_id
            for _ in range(20):
                if run_dir.is_dir():
                    break
                await asyncio.sleep(0.05)
            if run_dir.is_dir():
                raw = _att.load_raw(attachment_id)
                brief = _att.load_brief(attachment_id)
                if raw:
                    (run_dir / "raw_source.txt").write_text(raw)
                if brief:
                    (run_dir / "attachment_brief.md").write_text(brief)
                if att_meta:
                    (run_dir / "attachment.meta.json").write_text(json.dumps(att_meta, indent=2))
                if user_prompt:
                    (run_dir / "user_prompt.txt").write_text(user_prompt)
        except Exception:
            pass

    return JSONResponse({"run_id": run_id})


@app.get("/process")
async def process(
    idea: str,
    max_iterations: int = 5,
    vc_enabled: str = "1",
    user_id: str = "",
    persona: str = "",
    sector: str = "",
    stage: str = "",
    theme: str = "",
):
    """LEGACY: Kick off a run and stream events in one shot. Kept for back-compat
    on short ideas. Long ideas should use POST /runs/create + /stream/<run_id>.
    """
    if not idea.strip():
        async def empty():
            yield {"event": "error", "data": json.dumps({"message": "Empty idea."})}
        return EventSourceResponse(empty())

    max_iterations = max(1, min(20, int(max_iterations)))
    vc_on = str(vc_enabled).lower() not in ("0", "false", "no", "off", "")
    attribution = {
        "user_id": (user_id or "").strip()[:120] or "anonymous",
        "persona": normalize_persona(persona),
        "sector": normalize_sector(sector),
        "stage": normalize_stage(stage),
        "theme": (theme or "").strip()[:200],
    }
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]

    GUIDANCE_QUEUES[run_id] = asyncio.Queue()
    LIVE_RUNS[run_id] = {
        "task": None,
        "subscribers": [],
        "done": False,
        "started_at": datetime.utcnow().isoformat() + "Z",
        # Heartbeat support: each POST /heartbeat/<run_id> bumps this monotonic
        # timestamp. The guidance-fn timeout is measured relative to the latest
        # heartbeat, not the moment the panel appeared, so users who are
        # actively typing never get auto-skipped.
        "last_heartbeat_at": None,
    }

    # CRITICAL: subscribe BEFORE spawning the orchestrator task so the very
    # first emitted event reaches this client. If we created the task first,
    # the event loop could run it before _subscribe_sse appends our queue,
    # and early events (including run_started) would broadcast to an empty
    # subscriber list and be lost.
    subq: asyncio.Queue = asyncio.Queue()
    LIVE_RUNS[run_id]["subscribers"].append(subq)

    LIVE_RUNS[run_id]["task"] = asyncio.create_task(
        _run_orchestrator(idea, run_id, max_iterations, vc_on, attribution)
    )

    return EventSourceResponse(
        _drain_subscriber(run_id, subq),
        ping=SSE_PING_S,
    )


async def _drain_subscriber(run_id: str, subq: asyncio.Queue):
    """SSE generator that drains a pre-attached subscriber queue."""
    run_state = LIVE_RUNS.get(run_id)
    try:
        while True:
            ev = await subq.get()
            if ev.get("event") == "__END__":
                break
            yield {"event": ev["event"], "data": json.dumps(ev["data"])}
    finally:
        if run_state is not None:
            try:
                run_state["subscribers"].remove(subq)
            except ValueError:
                pass


@app.get("/stream/{run_id}")
async def stream(run_id: str):
    """Reconnect to an in-flight run. Subscribe FIRST (sync), then the
    generator replays on-disk history before draining the live queue.
    """
    run_state = LIVE_RUNS.get(run_id)
    subq: asyncio.Queue | None = None
    if run_state and not run_state["done"]:
        subq = asyncio.Queue()
        run_state["subscribers"].append(subq)
    return EventSourceResponse(_subscribe_sse(run_id, subq), ping=SSE_PING_S)


async def _subscribe_sse(run_id: str, subq: asyncio.Queue | None):
    """SSE generator for /stream/<run_id> reconnects.

    Caller must have already appended `subq` to the run's subscribers list
    (done synchronously in the endpoint before this generator runs).

    Replays on-disk events.ndjson first, then drains live events from subq.
    """
    run_state = LIVE_RUNS.get(run_id)
    try:
        events_path = RUNS_DIR / run_id / "events.ndjson"
        if events_path.is_file():
            try:
                for line in events_path.read_text().splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    yield {"event": rec["type"], "data": json.dumps(rec.get("data", {}))}
            except Exception as e:
                yield {"event": "error", "data": json.dumps({"message": f"Replay failed: {e}"})}

        if subq is None:
            # Run already completed — replay covered everything.
            return

        while True:
            ev = await subq.get()
            if ev.get("event") == "__END__":
                break
            yield {"event": ev["event"], "data": json.dumps(ev["data"])}
    finally:
        if subq is not None and run_state is not None:
            try:
                run_state["subscribers"].remove(subq)
            except ValueError:
                pass




RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


@app.get("/costs")
async def costs():
    """Scan runs/<id>/run.json files and return aggregate cost rollups."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())  # Monday
    month_start = today_start.replace(day=1)

    totals = {"today": 0.0, "week": 0.0, "month": 0.0, "all_time": 0.0}
    counts = {"today": 0, "week": 0, "month": 0, "all_time": 0}
    recent_runs: list[dict] = []

    if RUNS_DIR.exists():
        for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
            manifest_path = run_dir / "run.json"
            if not manifest_path.is_file():
                continue
            try:
                m = json.loads(manifest_path.read_text())
            except Exception:
                continue
            cost = float(((m.get("cost") or {}).get("total_usd")) or 0.0)
            started = m.get("started_at")
            try:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None
            except Exception:
                started_dt = None

            totals["all_time"] += cost
            counts["all_time"] += 1
            if started_dt:
                if started_dt >= today_start:
                    totals["today"] += cost
                    counts["today"] += 1
                if started_dt >= week_start:
                    totals["week"] += cost
                    counts["week"] += 1
                if started_dt >= month_start:
                    totals["month"] += cost
                    counts["month"] += 1

            if len(recent_runs) < 10:
                recent_runs.append({
                    "run_id": m.get("run_id"),
                    "started_at": started,
                    "status": m.get("status"),
                    "total_iterations": m.get("total_iterations"),
                    "final_score": m.get("final_score"),
                    "cost_usd": round(cost, 6),
                    "idea_preview": (m.get("idea") or "")[:120],
                })

    return JSONResponse({
        "totals_usd": {k: round(v, 6) for k, v in totals.items()},
        "counts": counts,
        "recent_runs": recent_runs,
        "window": {
            "today_start": today_start.isoformat(),
            "week_start": week_start.isoformat(),
            "month_start": month_start.isoformat(),
            "now": now.isoformat(),
        },
    })


@app.post("/resume/{run_id}")
async def resume(run_id: str, request: Request):
    """User submits strategic guidance (or empty to skip) for a paused run."""
    queue = GUIDANCE_QUEUES.get(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Unknown or completed run.")
    body = await request.json()
    guidance = (body.get("guidance") or "").strip()
    await queue.put(guidance)
    return JSONResponse({"ok": True, "skipped": guidance == ""})


@app.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, user_id: str = ""):
    """Cancel an in-flight run. Deletes its partial files.

    Ownership check: only the run's user_id (set at /process time) or an admin
    may stop. The orchestrator's asyncio.Task is cancelled, the in-memory state
    is cleaned, the partial run directory is removed.
    """
    import shutil
    state = LIVE_RUNS.get(run_id)
    if state is None:
        # Nothing in memory — could be a leftover dir from a crashed run.
        run_dir = RUNS_DIR / run_id
        if run_dir.is_dir():
            try:
                shutil.rmtree(run_dir)
                try:
                    from .run_index import delete_run as delete_run_index
                    delete_run_index(run_id)
                except Exception:
                    pass
                return JSONResponse({"ok": True, "was_running": False, "deleted_dir": True})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}")
        raise HTTPException(status_code=404, detail="Run not found.")

    # Identity gate
    requester = (user_id or "").strip()
    run_dir = RUNS_DIR / run_id
    owner = "anonymous"
    if (run_dir / "run.json").is_file():
        try:
            owner = (json.loads((run_dir / "run.json").read_text()).get("attribution") or {}).get("user_id") or "anonymous"
        except Exception:
            pass
    if not requester or (requester != owner and not is_admin(requester)):
        raise HTTPException(status_code=403, detail="Only run owner or admin may stop this run.")

    task = state.get("task")
    if task is not None and not task.done():
        task.cancel()
        # Give the orchestrator a brief moment to unwind its finally block.
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            pass

    # Tell any live SSE subscribers to close.
    for subq in list(state.get("subscribers") or []):
        try:
            subq.put_nowait({"event": "__END__", "data": {}})
        except Exception:
            pass

    # Drop in-memory state.
    LIVE_RUNS.pop(run_id, None)
    GUIDANCE_QUEUES.pop(run_id, None)

    # Delete the partial run directory.
    if run_dir.is_dir():
        try:
            shutil.rmtree(run_dir)
        except Exception as e:
            return JSONResponse({"ok": False, "stopped": True, "delete_error": str(e)})
        try:
            from .run_index import delete_run as delete_run_index
            delete_run_index(run_id)
        except Exception:
            pass

    return JSONResponse({"ok": True, "was_running": True, "deleted_dir": True})


@app.post("/runs/_cleanup_incomplete")
async def cleanup_incomplete_endpoint(user_id: str = ""):
    """Admin-only sweep: delete every run dir without status='completed'."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin only.")
    return JSONResponse(cleanup_incomplete_runs())


@app.post("/heartbeat/{run_id}")
async def heartbeat(run_id: str):
    """Client tells the server the user is actively typing in the guidance box.

    The guidance_fn poll loop checks `last_heartbeat_at` each second; once
    any heartbeat has arrived for the current iteration, the auto-skip
    deadline is suspended indefinitely. Only an explicit POST /resume
    advances the loop after that.
    """
    state = LIVE_RUNS.get(run_id)
    if state is None or state.get("done"):
        # Stale or unknown run; harmless no-op.
        return JSONResponse({"ok": True, "ignored": True})
    state["last_heartbeat_at"] = asyncio.get_running_loop().time()
    return JSONResponse({"ok": True})


@app.get("/runs/{run_id}/report.pdf")
async def report_pdf(run_id: str):
    """Bundle a completed run into a single PDF: cover + BRD + evolution + VC."""
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "run.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found or not yet finalized.")
    if not (run_dir / "final-brd.md").is_file():
        raise HTTPException(status_code=409, detail="Run is not complete; no final BRD yet.")
    try:
        pdf_bytes = render_run_pdf(run_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF render failed: {e}") from e

    project_title = extract_project_title(run_dir)
    slug = filename_slug(project_title, fallback=run_id)
    filename = f"minority_report_{slug}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/runs")
async def list_runs(
    user_id: str = "",
    sector: str = "",
    stage: str = "",
    persona: str = "",
    outcome: str = "",
    search: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """List runs from the SQLite index. user_id required (own runs only)
    unless requester is admin (then user_id="" returns everyone's)."""
    from .run_index import query_runs, rebuild_all
    requester = (user_id or "").strip()
    if not requester:
        raise HTTPException(status_code=403, detail="Identity required.")
    # Admin sees ALL runs (their own + everyone's). Non-admin sees own only.
    scope_uid = None if is_admin(requester) else requester
    # If the index file doesn't exist yet, rebuild it lazily.
    try:
        results = query_runs(
            user_id=scope_uid,
            sector=sector or None,
            stage=stage or None,
            persona=persona or None,
            outcome=outcome or None,
            search=search or None,
            limit=limit,
            offset=offset,
        )
    except Exception:
        rebuild_all()
        results = query_runs(
            user_id=scope_uid,
            sector=sector or None,
            stage=stage or None,
            persona=persona or None,
            outcome=outcome or None,
            search=search or None,
            limit=limit,
            offset=offset,
        )
    return JSONResponse({"runs": results, "count": len(results)})


@app.post("/runs/{run_id}/outcome")
async def update_outcome(run_id: str, request: Request, user_id: str = ""):
    """Record / update the real-world outcome for a run."""
    from .run_index import set_outcome
    requester = (user_id or "").strip()
    if not requester:
        raise HTTPException(status_code=403, detail="Identity required.")
    # Verify ownership or admin.
    manifest_path = RUNS_DIR / run_id / "run.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Run not found.")
    manifest = json.loads(manifest_path.read_text())
    owner = (manifest.get("attribution") or {}).get("user_id") or "anonymous"
    if requester != owner and not is_admin(requester):
        raise HTTPException(status_code=403, detail="Only owner or admin may update outcome.")
    body = await request.json()
    outcome = (body.get("outcome") or "").strip()
    note = (body.get("note") or "").strip()
    try:
        payload = set_outcome(run_id, outcome, note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found.")
    return JSONResponse({"ok": True, **payload})


CORPUS_KINDS = {"vc_memo", "investment_criteria", "past_pitch", "other"}


@app.get("/corpora")
async def list_corpora_endpoint(user_id: str = ""):
    """List the requester's corpora. Identity required."""
    from .run_index import list_corpora as _list
    if not user_id.strip():
        raise HTTPException(status_code=403, detail="Identity required.")
    return JSONResponse({"corpora": _list(user_id.strip())})


@app.post("/corpora")
async def create_corpus_endpoint(request: Request):
    """Create a new corpus. Body: {user_id, kind, label?, description?}."""
    from .run_index import create_corpus
    body = await request.json()
    uid = (body.get("user_id") or "").strip()
    kind = (body.get("kind") or "").strip()
    if not uid:
        raise HTTPException(status_code=403, detail="Identity required.")
    if kind not in CORPUS_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(CORPUS_KINDS)}")
    cid = create_corpus(
        owner_user_id=uid,
        kind=kind,
        label=(body.get("label") or "").strip()[:120],
        description=(body.get("description") or "").strip()[:1000],
    )
    return JSONResponse({"corpus_id": cid})


@app.delete("/corpora/{corpus_id}")
async def delete_corpus_endpoint(corpus_id: str, user_id: str = ""):
    from .run_index import delete_corpus
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=403, detail="Identity required.")
    if not delete_corpus(corpus_id, uid):
        raise HTTPException(status_code=404, detail="Corpus not found or you don't own it.")
    return JSONResponse({"ok": True})


@app.get("/corpora/{corpus_id}/items")
async def list_corpus_items_endpoint(corpus_id: str, user_id: str = ""):
    from .run_index import get_corpus, list_corpus_items
    cor = get_corpus(corpus_id)
    if not cor:
        raise HTTPException(status_code=404, detail="Corpus not found.")
    if cor["owner_user_id"] != user_id and not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Not yours.")
    return JSONResponse({"corpus": cor, "items": list_corpus_items(corpus_id)})


@app.post("/corpora/{corpus_id}/items")
async def add_corpus_item_endpoint(corpus_id: str, file: UploadFile = File(...), user_id: str = "", title: str = ""):
    """Upload one item (PDF/DOCX/TXT/MD) into a corpus.

    The item is extracted -> heuristic-stripped -> embedded (if Voyage is on).
    It is NOT distilled by default — for memos/criteria/pitches we want the
    real text retrievable verbatim. Distillation can be added per-corpus later.
    """
    from .run_index import get_corpus, add_corpus_item
    from .embeddings import is_available, embed
    cor = get_corpus(corpus_id)
    if not cor:
        raise HTTPException(status_code=404, detail="Corpus not found.")
    uid = (user_id or "").strip()
    if cor["owner_user_id"] != uid:
        raise HTTPException(status_code=403, detail="Not yours.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_BYTES // 1_048_576} MB.")
    try:
        result = extract_text(data, file.filename, file.content_type)
    except ExtractError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cleaned, _ = strip_noise(result.text)
    if not cleaned.strip():
        raise HTTPException(status_code=400, detail="No usable text in this file.")
    vec = None
    model = None
    if is_available():
        try:
            r = await embed(cleaned, input_type="document")
            vec, model = r["vector"], r["model"]
        except Exception:
            pass
    iid = add_corpus_item(
        corpus_id=corpus_id,
        title=(title or file.filename or "")[:200],
        content=cleaned,
        source_filename=file.filename,
        embedding=vec,
        embedding_model=model,
    )
    return JSONResponse({
        "item_id": iid,
        "embedded": vec is not None,
        "char_count": len(cleaned),
    })


@app.post("/runs/_backfill_embeddings")
async def backfill_embeddings(user_id: str = "", limit: int = 50):
    """Admin-only: embed any completed run that doesn't yet have an embedding.
    Returns counts. Safe to re-run; only un-embedded runs are processed."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin only.")
    from .embeddings import is_available, embed
    from .run_index import set_run_embedding, _conn
    if not is_available():
        raise HTTPException(status_code=412, detail="Voyage embeddings not configured (VOYAGE_API_KEY missing).")
    candidates: list[str] = []
    with _conn() as c:
        rows = c.execute(
            "SELECT run_id FROM runs WHERE embedding_json IS NULL AND status = 'completed' LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
        candidates = [r["run_id"] for r in rows]
    embedded = 0
    failed = 0
    for rid in candidates:
        brd_path = RUNS_DIR / rid / "final-brd.md"
        if not brd_path.is_file():
            failed += 1
            continue
        try:
            result = await embed(brd_path.read_text(), input_type="document")
            set_run_embedding(rid, result["vector"], result["model"])
            embedded += 1
        except Exception:
            failed += 1
    return JSONResponse({"considered": len(candidates), "embedded": embedded, "failed": failed})


@app.post("/runs/_rebuild_index")
async def rebuild_runs_index(user_id: str = ""):
    """Admin-only: rebuild the SQLite index from scratch."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin only.")
    from .run_index import rebuild_all
    n = rebuild_all()
    return JSONResponse({"ok": True, "indexed": n})


@app.get("/runs/{run_id}/similar")
async def similar_runs_endpoint(run_id: str, user_id: str = "", top_k: int = 5, scope: str = "self"):
    """Return runs whose final BRDs are semantically similar to this one.

    scope:
      - 'self' (default, privacy-safe): only runs owned by the same user.
      - 'all' (admin only): cross-user similarity — used internally / for ops.

    Tier 2.6 peer-run warnings will eventually use scope='peer' which needs
    anonymization + opt-in. Not built yet.
    """
    from .run_index import get_run_embedding, similar_runs as _similar
    if not (RUNS_DIR / run_id / "run.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found.")
    requester = (user_id or "").strip()
    if not requester:
        raise HTTPException(status_code=403, detail="Identity required.")
    vec, _model = get_run_embedding(run_id)
    if not vec:
        return JSONResponse({"matches": [], "reason": "Run not embedded (Voyage may be unavailable)."})

    # Owner / sector / stage of THIS run, used for filtered slicing.
    try:
        m = json.loads((RUNS_DIR / run_id / "run.json").read_text())
    except Exception:
        m = {}
    attr = m.get("attribution") or {}
    this_user = attr.get("user_id") or "anonymous"
    this_sector = attr.get("sector")
    this_stage = attr.get("stage")

    same_user_only = True
    if scope == "all":
        if not is_admin(requester):
            raise HTTPException(status_code=403, detail="scope='all' is admin-only.")
        same_user_only = False
    else:
        # Non-admin can only see own runs.
        if requester != this_user and not is_admin(requester):
            raise HTTPException(status_code=403, detail="Only run owner or admin may use this endpoint.")

    matches = _similar(
        vec,
        viewer_user_id=requester,
        same_user_only=same_user_only,
        exclude_run_id=run_id,
        top_k=max(1, min(20, int(top_k))),
    )
    return JSONResponse({
        "matches": matches,
        "context": {"run_id": run_id, "sector": this_sector, "stage": this_stage, "user_id": this_user},
    })


@app.get("/runs/{run_id}/refine")
async def refine_history(run_id: str, user_id: str = ""):
    """Return the existing refinement thread for a run."""
    from .refine import load_history
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "run.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found.")
    requester = (user_id or "").strip()
    try:
        owner = (json.loads((run_dir / "run.json").read_text()).get("attribution") or {}).get("user_id") or "anonymous"
    except Exception:
        owner = "anonymous"
    if requester and requester != owner and not is_admin(requester):
        raise HTTPException(status_code=403, detail="Only run owner or admin may view this thread.")
    return JSONResponse({"thread": load_history(run_dir)})


@app.post("/runs/{run_id}/refine")
async def refine_turn(run_id: str, request: Request, user_id: str = ""):
    """Take one turn in the post-loop refinement chat. Returns the assistant reply."""
    from .refine import refine
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "run.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found.")
    if not (run_dir / "final-brd.md").is_file():
        raise HTTPException(status_code=409, detail="Run has no final BRD yet.")
    requester = (user_id or "").strip()
    try:
        owner = (json.loads((run_dir / "run.json").read_text()).get("attribution") or {}).get("user_id") or "anonymous"
    except Exception:
        owner = "anonymous"
    if not requester or (requester != owner and not is_admin(requester)):
        raise HTTPException(status_code=403, detail="Only run owner or admin may refine this run.")
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty refinement message.")
    try:
        record = await refine(run_dir, message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Refine call failed: {e}") from e
    return JSONResponse({"assistant": record})


@app.delete("/runs/{run_id}")
async def delete_run(run_id: str, user_id: str = ""):
    """Delete a run's directory. Owner-only (the user who created it) or admin.

    The flag-pattern index is rebuilt so deleted runs stop contributing to priors.
    """
    import shutil
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "run.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found.")
    # Identity gate: must be the run's owner or admin.
    try:
        manifest = json.loads((run_dir / "run.json").read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read manifest: {e}")
    owner = (manifest.get("attribution") or {}).get("user_id") or "anonymous"
    requester = (user_id or "").strip()
    if not requester:
        raise HTTPException(status_code=403, detail="Identity required to delete a run.")
    if requester != owner and not is_admin(requester):
        raise HTTPException(status_code=403, detail="Only the run owner or an admin may delete this run.")
    try:
        shutil.rmtree(run_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")
    # Rebuild the priors index since this run no longer contributes.
    try:
        rebuild_flag_patterns()
    except Exception:
        pass
    # Remove from the runs index too.
    try:
        from .run_index import delete_run as delete_run_index
        delete_run_index(run_id)
    except Exception:
        pass
    return JSONResponse({"ok": True, "deleted": run_id})


@app.post("/feedback/{run_id}")
async def submit_feedback(run_id: str, request: Request):
    """Capture post-run user feedback. Rebuilds the flag-pattern index so
    feedback signal feeds into the next run's premortem priors immediately.
    """
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "run.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found.")
    body = await request.json()
    rating = (body.get("rating") or "").strip().lower()
    if rating not in ("up", "down", "acted_on"):
        raise HTTPException(status_code=400, detail="rating must be 'up', 'down', or 'acted_on'.")
    note = (body.get("note") or "").strip()
    most_useful_n = body.get("most_useful_iteration_n")
    try:
        most_useful_n = int(most_useful_n) if most_useful_n is not None else None
    except (TypeError, ValueError):
        most_useful_n = None
    payload = {
        "rating": rating,
        "note": note,
        "most_useful_iteration_n": most_useful_n,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
    }
    (run_dir / "feedback.json").write_text(json.dumps(payload, indent=2))
    try:
        rebuild_flag_patterns()
    except Exception:
        pass
    return JSONResponse({"ok": True})


@app.get("/whoami")
async def whoami(user_id: str = ""):
    """Tell the client whether the current identity has admin privileges."""
    return JSONResponse({"is_admin": is_admin(user_id)})


@app.get("/analytics")
async def analytics(user_id: str = ""):
    """Admin analytics — all runs, ops view. Gated by user_id."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return JSONResponse(compute_analytics())


@app.get("/admin/feedback/status")
async def admin_feedback_status(user_id: str = ""):
    """Tiny status payload: feedback count, threshold, stale flag, cache time."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin only.")
    from .feedback_analysis import feedback_status
    return JSONResponse(feedback_status())


@app.get("/admin/feedback/analyze")
async def admin_feedback_analysis_cached(user_id: str = ""):
    """Return the cached analysis (no LLM call). Use POST to re-run."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin only.")
    from .feedback_analysis import load_cached_analysis, feedback_status
    cached = load_cached_analysis()
    return JSONResponse({"cached": cached, "status": feedback_status()})


@app.post("/admin/feedback/analyze")
async def admin_feedback_analysis_run(user_id: str = ""):
    """Run a fresh cross-run feedback analysis. Caches the result."""
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin only.")
    from .feedback_analysis import analyze
    try:
        result = await analyze()
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e}") from e
    return JSONResponse(result)


@app.get("/analytics/outcome_distribution")
async def outcome_distribution(user_id: str = "", scope: str = "self"):
    """Sector x stage x score-band -> outcome distribution. Used to power
    'in your sector at score 84, X% historically ended in failure' KPIs.

    scope: 'self' (default) or 'all' (admin).
    """
    from .run_index import _conn
    requester = (user_id or "").strip()
    if not requester:
        raise HTTPException(status_code=403, detail="Identity required.")
    same_user_only = True
    if scope == "all":
        if not is_admin(requester):
            raise HTTPException(status_code=403, detail="scope='all' is admin-only.")
        same_user_only = False
    with _conn() as c:
        sql = """SELECT sector, stage, final_score, outcome FROM runs
                 WHERE status='completed' AND outcome IS NOT NULL AND outcome != 'unset'"""
        params: list = []
        if same_user_only:
            sql += " AND user_id = ?"
            params.append(requester)
        rows = c.execute(sql, params).fetchall()
    # Aggregate by (sector, stage, score_band).
    from collections import defaultdict
    agg: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        score = r["final_score"] if r["final_score"] is not None else -1
        band = "70-79" if 70 <= score < 80 else "80-89" if 80 <= score < 90 else "90+" if score >= 90 else "<70"
        key = (r["sector"] or "unspecified", r["stage"] or "unspecified", band)
        agg[key][r["outcome"]] += 1
        agg[key]["__total__"] += 1
    out = []
    for (sector, stage, band), counts in agg.items():
        total = counts.pop("__total__", 0)
        failures = sum(counts.get(k, 0) for k in ("declined", "passed", "killed"))
        successes = sum(counts.get(k, 0) for k in ("invested", "built", "advanced"))
        out.append({
            "sector": sector,
            "stage": stage,
            "score_band": band,
            "total": total,
            "by_outcome": dict(counts),
            "failure_rate": round(failures / total, 4) if total else 0.0,
            "success_rate": round(successes / total, 4) if total else 0.0,
        })
    out.sort(key=lambda x: (-x["total"], x["sector"], x["stage"], x["score_band"]))
    return JSONResponse({"rows": out, "scope": scope, "viewer": requester})


@app.get("/analytics/user")
async def analytics_user(user_id: str = "", persona: str = ""):
    """User-facing analytics — filtered to one user, framed for value delivered."""
    uid = (user_id or "").strip() or None
    p = (persona or "").strip() or None
    return JSONResponse(compute_analytics(user_id=uid, persona=p, mode="user"))


@app.get("/personas")
async def personas():
    """Persona registry for the intake form."""
    return JSONResponse({
        "personas": [
            {"id": k, "label": v["label"], "baseline_minutes": v["baseline_minutes"], "description": v["description"]}
            for k, v in PERSONAS.items()
        ]
    })


@app.get("/rubric")
async def get_rubric(user_id: str = "", persona: str = ""):
    """Return the user's tuned rubric weights + whether tuning is allowed."""
    from .rubric import get_weights, TUNABLE_PERSONAS, DEFAULT_WEIGHTS
    p = (persona or "").strip().lower()
    return JSONResponse({
        "weights": get_weights(user_id or ""),
        "defaults": dict(DEFAULT_WEIGHTS),
        "tunable": p in TUNABLE_PERSONAS,
        "tunable_personas": sorted(TUNABLE_PERSONAS),
    })


@app.post("/rubric")
async def set_rubric(request: Request):
    """Investor-persona only: persist custom pillar weights."""
    from .rubric import set_weights
    body = await request.json()
    uid = (body.get("user_id") or "").strip()
    persona = (body.get("persona") or "").strip()
    weights = body.get("weights") or {}
    if not uid:
        raise HTTPException(status_code=403, detail="Identity required.")
    try:
        saved = set_weights(uid, persona, weights)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"ok": True, "weights": saved})


@app.get("/taxonomy")
async def taxonomy():
    """Sector + stage dropdowns for the intake form."""
    return JSONResponse({
        "sectors": [{"id": s, "label": s.replace("_", " ").title()} for s in SECTORS],
        "stages": [{"id": s, "label": s.replace("_", " ").title()} for s in STAGES],
    })


@app.get("/analytics/flag-patterns")
async def analytics_flag_patterns():
    """Raw flag-pattern priors currently being injected into premortems."""
    return JSONResponse(load_flag_patterns())


@app.post("/distill")
async def distill_endpoint(request: Request):
    """Two-step: heuristic strip -> Haiku distill. Returns brief + stats + cost.

    Client posts {text: "<raw>"}, receives:
      {cleaned, brief, raw_chars, cleaned_chars, brief_chars, cost_usd, model, stats}

    No persistence here — the brief comes back, user edits it, and only the
    final (possibly edited) brief plus the raw extract are saved when /runs/create
    is called.
    """
    body = await request.json()
    raw = (body.get("text") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty text.")
    if len(raw) > 250_000:  # ~250 KB cap; PDFs above this are extreme
        raise HTTPException(status_code=413, detail="Text exceeds 250 KB cap for distillation.")

    cleaned, stats = strip_noise(raw)
    try:
        brief, usage = await distill(cleaned)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Distill failed: {e}") from e

    return JSONResponse({
        "cleaned": cleaned,
        "brief": brief,
        "raw_chars": len(raw),
        "cleaned_chars": len(cleaned),
        "brief_chars": len(brief),
        "model": usage.model,
        "cost_usd": round(usage.cost_usd, 6),
        "stats": stats,
    })


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Accept a PDF / DOCX / TXT / MD upload, extract + strip + distill it
    server-side, store as an attachment, and return only its id + stats.

    The textarea is NOT populated with the file text. The file lives in the
    backend as an attachment; the user types their own prompt; at /runs/create
    time the two are composed into one idea passed to the orchestrator.
    """
    from . import attachments as _att

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_BYTES // 1_048_576} MB limit.",
        )

    try:
        result = extract_text(data, file.filename, file.content_type)
    except ExtractError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}") from e

    raw_text = result.text
    cleaned, strip_stats = strip_noise(raw_text)

    # Distill ONLY when the cleaned text is genuinely large (>40 KB). Most
    # decks / BRDs / one-pagers fit easily under that; sending them raw to the
    # brainstorm gives Sonnet/Opus the full signal. Distillation is a *cost
    # control* for massive uploads (e.g. multi-hundred-page market reports),
    # not the default mode.
    DISTILL_THRESHOLD = 40 * 1024  # 40 KB
    if len(cleaned) < DISTILL_THRESHOLD:
        brief = cleaned
        usage_dict = {"model": MODELS["distill"], "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "skipped": True}
    else:
        try:
            brief, usage = await distill(cleaned)
            usage_dict = usage.to_dict()
        except Exception as e:
            brief = cleaned
            usage_dict = {"model": MODELS["distill"], "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "error": str(e)}

    meta = _att.create(
        raw_text=raw_text,
        cleaned_text=cleaned,
        brief=brief,
        filename=file.filename,
        kind=result.source_kind,
        pages=result.pages,
        raw_chars=len(raw_text),
        cleaned_chars=len(cleaned),
        brief_chars=len(brief),
        strip_stats=strip_stats,
        usage=usage_dict,
    )
    return JSONResponse({
        "attachment_id": meta["id"],
        "filename": meta["filename"],
        "kind": meta["kind"],
        "pages": meta["pages"],
        "raw_chars": meta["raw_chars"],
        "cleaned_chars": meta["cleaned_chars"],
        "brief_chars": meta["brief_chars"],
        "distill_cost_usd": usage_dict.get("cost_usd", 0.0),
    })


@app.get("/attachments/{attachment_id}/brief")
async def attachment_brief(attachment_id: str):
    """Return the distilled brief for an attachment — used by the
    'view what the system understood from this file' reveal in the UI.
    """
    from . import attachments as _att
    meta = _att.load_meta(attachment_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    brief = _att.load_brief(attachment_id) or ""
    return JSONResponse({"meta": meta, "brief": brief})


@app.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str):
    from . import attachments as _att
    if not _att.delete(attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return JSONResponse({"ok": True})
