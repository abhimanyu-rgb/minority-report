"""FastAPI app: idea form + SSE stream of the brainstorm/premortem loop with strategic-pause."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

load_dotenv()

from .orchestrator import Orchestrator  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Minority Report")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Per-run guidance queues. The orchestrator awaits a put; the resume endpoint
# puts the user's text. A None value means "skip" (treated as empty string).
GUIDANCE_QUEUES: dict[str, asyncio.Queue[str]] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/process")
async def process(idea: str, max_iterations: int = 5):
    """SSE endpoint. Streams events from the orchestrator."""
    if not idea.strip():
        async def empty():
            yield {"event": "error", "data": json.dumps({"message": "Empty idea."})}
        return EventSourceResponse(empty())

    max_iterations = max(1, min(20, int(max_iterations)))

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    queue: asyncio.Queue[str] = asyncio.Queue()
    GUIDANCE_QUEUES[run_id] = queue

    async def guidance_fn(iteration: int, top_issues: list[dict]) -> str:
        # Block until /resume puts something for this run.
        return await queue.get()

    orch = Orchestrator()

    async def event_gen():
        try:
            async for ev in orch.run(idea, run_id=run_id, guidance_fn=guidance_fn, max_iterations=max_iterations):
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
        finally:
            GUIDANCE_QUEUES.pop(run_id, None)

    return EventSourceResponse(event_gen())


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
