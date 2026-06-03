"""FastAPI app: idea form + SSE stream of the brainstorm/premortem loop with strategic-pause."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

load_dotenv()

from .orchestrator import Orchestrator  # noqa: E402
from .report_pdf import render_run_pdf, extract_project_title, filename_slug  # noqa: E402

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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


async def _run_orchestrator(idea: str, run_id: str, max_iterations: int) -> None:
    """Background task: runs the orchestrator, pushes each event to all subscribers."""
    run_state = LIVE_RUNS[run_id]
    guidance_queue: asyncio.Queue[str] = GUIDANCE_QUEUES[run_id]

    async def guidance_fn(iteration: int, top_issues: list[dict], timeout_s: int) -> str:
        try:
            return await asyncio.wait_for(guidance_queue.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return ""

    orch = Orchestrator()
    try:
        async for ev in orch.run(idea, run_id=run_id, guidance_fn=guidance_fn, max_iterations=max_iterations):
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


@app.get("/process")
async def process(idea: str, max_iterations: int = 5):
    """Kick off a run and stream its events. Run survives this connection."""
    if not idea.strip():
        async def empty():
            yield {"event": "error", "data": json.dumps({"message": "Empty idea."})}
        return EventSourceResponse(empty())

    max_iterations = max(1, min(20, int(max_iterations)))
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]

    GUIDANCE_QUEUES[run_id] = asyncio.Queue()
    LIVE_RUNS[run_id] = {
        "task": None,
        "subscribers": [],
        "done": False,
        "started_at": datetime.utcnow().isoformat() + "Z",
    }

    # CRITICAL: subscribe BEFORE spawning the orchestrator task so the very
    # first emitted event reaches this client. If we created the task first,
    # the event loop could run it before _subscribe_sse appends our queue,
    # and early events (including run_started) would broadcast to an empty
    # subscriber list and be lost.
    subq: asyncio.Queue = asyncio.Queue()
    LIVE_RUNS[run_id]["subscribers"].append(subq)

    LIVE_RUNS[run_id]["task"] = asyncio.create_task(
        _run_orchestrator(idea, run_id, max_iterations)
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
