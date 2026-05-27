# Minority Report

Locally-deployed app that turns a brief business idea into a green-lit Business Requirements Document (BRD), by recursively looping a **technical brainstorm** stage against a **premortem evaluator** until the plan passes a bar (score ≥ 80 and zero red flags), capped at 5 iterations.

## How it works

```
   idea
    │
    ▼
┌───────────────────┐
│ technical         │◀──────┐
│ brainstorm  →BRD  │       │
└─────────┬─────────┘       │
          ▼                 │ revision prompt
┌───────────────────┐       │ (red/yellow flags)
│ premortem         │───────┘
│ →score + flags    │
└─────────┬─────────┘
          │
   score ≥ 80 AND
   zero red flags?
          │
   yes ─► publish final BRD + future success score
   no  ─► re-process (back into brainstorm)
   cap ─► publish best-scoring draft with warning banner
```

Each iteration is persisted under `runs/<run-id>/` (BRD versions + premortem JSON + final).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
# put your real ANTHROPIC_API_KEY in .env
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000, paste an idea, press **Process this idea**, watch iterations stream in.

## Configuration (env vars)

- `ANTHROPIC_API_KEY` — required
- `BRAINSTORM_MODEL` — default `claude-sonnet-4-6`
- `PREMORTEM_MODEL` — default `claude-sonnet-4-6`
- `MAX_ITERATIONS` — default `5`
- `SCORE_THRESHOLD` — default `80`

## Layout

```
app/
  main.py            FastAPI + SSE endpoint
  orchestrator.py    The brainstorm/premortem loop
  prompts.py         System prompts for both stages
  templates/         index.html
  static/            style.css, app.js
runs/                Persisted iterations per run
.claude/skills/      technical-brainstorm skill (reference, not invoked)
```

The `technical-brainstorm` skill in `.claude/skills/` is an interactive skill for Claude Code. We use its *philosophy* (every decision needs Why + How-to-apply, present-tense greenfield writing, explicit non-goals vs rejected vs backlog, etc.) by distilling it into the `BRAINSTORM_SYSTEM` prompt in [app/prompts.py](app/prompts.py); we do not call the slash-command skill at runtime.
