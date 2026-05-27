# technical-brainstorm

A Claude Code skill for **structured design of unbuilt software**. It enforces a deliberate plan-before-code phase, captures decisions and open questions in a persistent registry of pillar documents, and refuses to write production code while a session is open.

The user's job is to prevent eager coding. The skill's job is to make planning the path of least resistance.

---

## Why this skill exists

The default failure mode of an AI assistant on a fresh problem is to **start typing code immediately**. That produces:

- Decisions made implicitly inside `src/`, never written down.
- Open questions silently resolved with the first plausible answer.
- Architecture that drifts because no one tracked the "why".
- Re-work when the next session forgets context the previous one had.

`technical-brainstorm` inverts this. While a session is open, the skill behaves as a **design facilitator** — not a coder. It asks structured questions, records answers into named files, and uses a state file (`state.md`) to remember across conversations whether a session is active. Code authoring is **blocked** outside the brainstorm folder; small load-bearing snippets are allowed only as illustration inside it.

The output is not a single document. It is a **registry** — nine pillar files plus numbered plan docs — that survives across sessions and stays load-bearing because every entry has a *why*.

---

## When to use it

Good fits:

- New system being designed from scratch.
- New feature on a system that hasn't shipped yet.
- Migration or refactor with enough surface area that you want decisions captured before code.
- Multi-service or cross-team design needing a shared registry of decisions.

Bad fits — the skill will say so and offer to redirect:

- Debugging a specific bug in an existing system.
- One-day scripts, single-button additions, typo fixes.
- Established codebases where you're following an existing pattern.
- Anything where the right next step is to read or change code, not to decide.

When the skill detects a bad fit during qualification, it asks the user before exiting — never bails unilaterally. The user can override and proceed anyway.

---

## Installation

In this repo (`etna`), the skill lives at:

```
store/skills/technical-brainstorm/
├── SKILL.md            # The skill definition Claude Code loads.
├── README.md           # This file.
├── greenfield.md       # Writing doctrine for greenfield architecture docs.
└── templates/          # Pillar file templates copied into ./plan/ on first use.
    ├── state.md
    ├── questions.md
    ├── decisions.md
    ├── doctrine.md
    ├── glossary.md
    ├── inventory.md
    ├── non-goals.md
    ├── references.md
    ├── rejected.md
    ├── milestones.md
    └── plan-doc.md
```

To use the skill in a project, place the folder at one of:

- `~/.claude/skills/technical-brainstorm/` (user-wide install)
- `<project>/.claude/skills/technical-brainstorm/` (project-scoped install)
- A plugin under `<project>/plugins/<plugin>/skills/technical-brainstorm/`

Claude Code loads any skill whose `SKILL.md` it can discover via its standard skill resolution.

---

## Lifecycle

The skill exposes exactly two subcommands. Everything else happens **within** an active session as natural conversation.

```
/technical-brainstorm start    # open a session
/technical-brainstorm close    # close a session
```

There is no `sweep`, `check`, `resolve`, `init`, or `reinforce` subcommand. The skill reads `state.md` at the start of every turn to decide whether a session is open, and adapts behavior accordingly.

### `start` — opening a session

1. **Qualification** — 2–4 questions via `AskUserQuestion`: what's being designed, what's built so far, rough scope, whether the goal is to lock decisions before code. If the answers suggest a poor fit, the skill says so and offers to redirect (dump conversation into a temp file and end before opening). The user always decides.

2. **Folder selection** — Decide where pillars and `state.md` live. The skill scans the working directory (one level deep) for candidate folders:
   - Conventional names: `./plan/`, `./brainstorm/`, `./design/`.
   - Any other folder containing `state.md` plus at least one pillar file.

   Resolution:
   - **One candidate** → confirm in a single line.
   - **Multiple candidates** → present via `AskUserQuestion`.
   - **None found** → ask the user; offer the conventional names plus "Other" for a custom path.

   The chosen folder anchors the entire session. Every later reference to `./plan/` resolves to it.

3. **Bootstrap** — Copy any missing pillar files from `templates/` into the chosen folder. Existing files are never overwritten. Write `state.md` with `STATE: open`, session start date, and the current topic.

4. **Source materials (optional)** — Before intake, the skill asks whether existing documents or projects should inform the design. If yes, it copies them into `./plan/sources/` and adds entries to `references.md` so the session works off local copies rather than thrashing across the filesystem.

5. **Intake interview** — `AskUserQuestion` in topical bundles (2–4 questions per batch) seeds the pillars: what the system is for, what's explicitly not being built, prior art, hard constraints, obvious open questions. Each answer is written directly to the relevant pillar as it comes in — no accumulating in conversation.

6. **First-pass review** — Show the user the pillar summaries, the open-questions dependency graph (computed from `Blocks.` fields, presented topologically), and the next milestone's blocking questions. Ask which question to tackle first.

### In-session behavior

Once `state.md` is `STATE: open`, the skill is active across all subsequent turns until `close` runs.

#### Voices

The skill's tone shifts implicitly based on what's happening — no flags or overrides.

| Phase | Voice | What this means |
|---|---|---|
| Intake | **Facilitator** | Neutral. Open questions. Draw out intent. Don't propose. |
| Surfacing new topics | **Architect mentor** | Proactively raise things the user hasn't named. Cite prior art. |
| Resolving a question | **Sparring partner** | Push back on weak rationale. Name the unstated tradeoff. |
| Sweeps, status reads, capture | **Scribe** | Pure capture. Don't editorialize. |
| `close` and gap detection | **Critic** | Look for inconsistencies, smell-words, underspecified pillars. |

#### Writing recommendations on questions

When the skill surfaces a new question or sweeps the question ledger, it adds a one-line **Claude's take:** field to questions where it has a confident view. **Silent on uncertain questions** — a hedge is worse than nothing. When the take disagrees with an existing Lean, it says so explicitly.

#### Resolving a question

1. Read the full question from `questions.md`.
2. Present options via `AskUserQuestion`. If the user has already named an answer in chat, pre-lean it with a confirm step.
3. **Sparring-partner pushback**: probe weak rationale once. If the user holds firm, accept.
4. Append to `decisions.md` with **Decision**, **Why**, **How to apply**, **Resolves Q-N**, optional **Alternatives considered** linking to `rejected.md`.
5. **Delete** Q-N from `questions.md`. No strikethrough. No "(resolved)" marker. The decision now lives in `decisions.md`, period.

#### Topic shifts → pillar reinforcement

When conversation moves from one design topic to another, the skill pauses **before** entering the new topic:

> "I see we're moving from [previous] to [next]. Before we shift — do any of these belong in the load-bearing pillars?
> - [Candidate 1] → could go in `glossary.md` because [reason]
> - [Candidate 2] → could go in `doctrine.md` because [reason]
>
> Promote any of them?"

This is the **only** periodic prompt. There is no scheduled checkpoint or review — pillar reinforcement happens at natural topic boundaries because that's when the closing context is fresh.

#### Semantic sweeps

When the user asks to "update the docs" / "propagate this", the skill runs a semantic sweep — not a grep:

1. List all plan docs and pillar files that might be affected.
2. Read each end-to-end for sections referencing the changed concept.
3. Present a punch list grouped by file → section → proposed edit.
4. Wait for approval before editing.

Sweeps are **never automatic**. They are user-requested or skill-recommended, but the user always pulls the trigger.

#### Production code — blocked

The skill refuses to write production code (in `src/`, `apps/`, `packages/`, etc.) while a session is open. Small load-bearing snippets — a config sketch, an API contract, a database row layout — are allowed **inside the brainstorm folder** in `./plan/samples/` or inline in plan docs as fenced code. They are documentation, not production.

If the user asks for production code, the skill says:

> "We're in an active brainstorm session. I can sketch this inside `./plan/` as illustration, or you can run `/technical-brainstorm close` first if you want to start building. Which do you want?"

### `close` — closing a session

1. Read all pillars and plan docs.
2. Run gap detection:
   - Greenfield smell-words grep across plan docs (see `greenfield.md`).
   - Decisions missing **Why** or **How to apply**.
   - Questions with no `Blocks.` field.
   - Pillars untouched since `start` (suggests underspecified design).
   - Plan docs with their own "Open Questions" section instead of a pointer to `questions.md`.
3. Report gaps — do not auto-fix.
4. Ask whether to address them now or close anyway.
5. On confirmation, write `STATE: closed` to `state.md` with a one-line reason (milestone reached / paused / scope cut / handing off).
6. If `./plan/sources/` exists, offer to delete it. Default to keep if unclear — they were copies; originals are untouched.
7. Print: "Run `/technical-brainstorm start` to resume."

---

## The 9 pillars (+ plan docs)

| File | Role |
|---|---|
| `questions.md` | Live ledger of unresolved decisions. Self-contained text per question (no `08 §5` cross-refs). |
| `decisions.md` | Resolved decisions, each with **Why** and **How to apply**. Append-only. |
| `doctrine.md` | Stable principles that pre-answer future questions. |
| `glossary.md` | Project-specific terms with definitions. |
| `inventory.md` | What exists / is being built / is external / is reference-only. |
| `non-goals.md` | Explicit "not building" list, each with a reason. |
| `references.md` | External prior art, each with a one-line "what we use it for". |
| `rejected.md` | Alternatives considered and rejected, with reasons + re-evaluate conditions. |
| `milestones.md` | Sequencing only. Each milestone names its blocking questions and dependencies. |

Plus **plan docs** — `01-foo.md`, `02-bar.md`, ... — domain-by-domain architecture, present-tense. Format described in `templates/plan-doc.md`.

Each template at `templates/` carries a full prose introduction. Read the template, not summaries, when working with format details.

---

## Hard rules

These hold for the entire session.

1. **No production code outside the brainstorm folder.** Small load-bearing snippets go in `./plan/samples/` or inline in plan docs. Never touch `src/`, `apps/`, `packages/`.
2. **Resolved questions get DELETED, not struck through.** No `~~`, no "(resolved)", no "previously planned".
3. **Self-contained registry.** Full text in `questions.md`. Never `08 §5` cross-references that force a second read.
4. **Every decision carries Why + How to apply.** Without the *why*, future-you can't judge edge cases.
5. **Reference implementations beat invented solutions.** If prior art exists, link in `references.md` and use it. Don't re-derive.
6. **Batch questions via `AskUserQuestion`**, 2–4 at a time. Never open-chat dump structured choices.
7. **Greenfield writing rules apply** to all docs in the brainstorm folder. See `greenfield.md`.
8. **No past tense for software that doesn't exist yet.** Architecture docs are present-tense. The past lives only in `decisions.md`, `rejected.md`, `references.md`, and git history.

---

## State management

`state.md` is the source of truth for session lifecycle. Format:

```
STATE: open | closed
SESSION STARTED: <ISO date>
SESSION CLOSED: <ISO date or absent>
CURRENT TOPIC: <one-line>
LAST UPDATED: <ISO date>
```

- `STATE: open` → in-session behavior applies (voices, refusal rules, topic-shift prompts).
- `STATE: closed` → the skill does nothing on its own; only `/technical-brainstorm start` re-opens it.
- `CURRENT TOPIC` updates on every detected topic shift.
- `LAST UPDATED` updates on every pillar write.

To find `state.md` across turns, the skill checks the conventional folders (`./plan/`, `./brainstorm/`, `./design/`) and any other one-level-deep folder containing pillar files.

---

## Greenfield doctrine

`greenfield.md` is loaded for any sweep, gap detection, or `close`. It enforces a single rule for unbuilt-software docs:

> Describe what the system **is** (or will be — same thing in greenfield). Never describe what it isn't, used to be, replaces, supersedes, or is migrating from.

The doctrine includes a banned-patterns table (no "X replaces Y", no `~~strike-through~~`, no "previously planned", no "(resolved)" markers) and a `grep` smell-words check that `close` runs automatically. Hits are acceptable only in `decisions.md`, `rejected.md`, `references.md`, commit messages, and `./plan/sources/`.

The full doctrine, including the four places where the past *does* belong, lives in `greenfield.md`.

---

## Design philosophy

A few choices in this skill are deliberate and worth naming:

**Skill behavior is determined by state, not by flags.** Voices, refusal rules, and topic-shift prompts all derive from `state.md` and the current phase. The user shouldn't have to specify "use facilitator voice" or "stop refusing code now" — the skill should read context and act.

**Capture is part of conversation, not a separate ceremony.** Pillar updates happen inline as topics come up, not at end-of-session. The skill writes to files during the same turn that elicits the information.

**Resolved questions disappear from the ledger.** Striking-through or marking "(resolved)" creates noise that future readers — including future Claude — have to filter. The decision lives in `decisions.md`; the question is gone.

**Why** is load-bearing. Every decision and every piece of feedback-style guidance carries a *why*. Without it, future-you can't judge edge cases — only blindly follow or blindly violate the rule.

**The user prevents eager coding.** The skill is the assistant. The user controls when a session opens and closes. There is no "auto-open on natural language phrases like let's design" — that pattern has caused too many surprise refusals when the user just wanted to chat. The skill opens only on explicit `/technical-brainstorm start`.

**Reference implementations beat invented solutions.** If prior art exists for the problem, the skill prefers a one-line link in `references.md` over a re-derivation. Originality is not a virtue when shipping is the goal.

---

## Anti-features (what this skill deliberately doesn't do)

- **No auto-invocation on natural language.** Phrases like "let's plan", "let's design", "let's think through X" do **not** trigger the skill. Only explicit `/technical-brainstorm start` and `/technical-brainstorm close` do.
- **No automatic semantic sweeps.** Sweeps run only when the user asks or when the skill recommends one after a major decision and the user agrees.
- **No scheduled checkpoints.** Pillar reinforcement happens at natural topic boundaries — the only periodic prompt.
- **No subcommand sprawl.** No `sweep`, `resolve`, `init`, `reinforce`, `check`. Two verbs total: `start` and `close`.
- **No code in `src/`.** The skill will refuse and offer a sketch inside the brainstorm folder or a close-then-build path.

---

## Related

- `greenfield.md` — writing doctrine for unbuilt-software docs.
- `templates/` — pillar file templates, each with a prose introduction describing its format.
- The `documentation` skill in this repo handles documentation of *built* systems (changelogs, ADRs, root READMEs). `technical-brainstorm` is its before-the-fact counterpart.
