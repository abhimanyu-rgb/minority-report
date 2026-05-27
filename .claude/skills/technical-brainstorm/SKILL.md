---
name: technical-brainstorm
description: Structured planning/design session for software that hasn't been built yet. Invoked ONLY by explicit slash commands `/technical-brainstorm start` and `/technical-brainstorm stop`. Do NOT auto-invoke on natural-language phrases like "let's plan", "let's design", "let's think through X", or any other phrasing — those are not triggers. The skill maintains 10 pillar documents (questions, decisions, doctrine, glossary, inventory, non-goals, references, rejected, milestones, backlog) inside a `pillars/` subfolder, plus a top-level `state.md` tracking session open/closed AND the active mode (explore / decide / step-back). Refuses to write production code outside the brainstorm folder while a session is active.
argument-hint: "start | stop"
---

# Technical Brainstorm

Plan and design before building. While a session is active, capture concerns, hypotheses, and decisions into a registry of pillar documents that survives across conversations.

The user's job is to prevent eager coding. The skill's job is to make the planning conversation feel like a conversation — not an interview, not a decision-extraction funnel.

## Two subcommands. That's it.

- `/technical-brainstorm start` — open a session
- `/technical-brainstorm stop` — stop a session

Everything else happens **within** an active session, as natural conversation. There is no `sweep`, `check`, `resolve`, `init`, `reinforce`, `commit`, or `rescind` subcommand. The skill behaves correctly without ceremony — it reads `state.md` on every turn to know whether a session is open and what mode it is in, and adapts its voice and tool-use posture accordingly.

## Folder layout

Every brainstorm session lives in a single folder (`./plan/`, `./brainstorm/`, `./design/`, or a custom path picked at session start). Inside that folder:

```
./plan/                              # session anchor
├── state.md                         # session lifecycle + mode — TOP LEVEL (never inside pillars/)
├── pillars/                         # all pillar docs
│   ├── questions.md
│   ├── decisions.md
│   ├── doctrine.md
│   ├── glossary.md
│   ├── inventory.md
│   ├── non-goals.md
│   ├── references.md
│   ├── rejected.md
│   ├── milestones.md
│   └── backlog.md
├── sources/                         # optional — source materials copied in for the session
├── samples/                         # optional — load-bearing code snippets (illustrative)
├── 01-foo.md                        # plan docs (numbered by domain)
├── 02-bar.md
└── 01-foo-v0.1.md / 01-foo-v0.2.md  # plan-doc version drafts (see "Plan-doc versioning")
```

**`state.md` stays at the top level.** It is the session-lifecycle gate the skill reads every turn — folder-scan logic uses it to detect an active session. It is not a pillar.

**All 10 pillars live in `pillars/`.** Cross-references inside session docs use `pillars/<name>.md` paths.

Three of the pillars handle related-but-distinct scope concerns; mixing them is a common mistake:

| Pillar | Semantics |
|---|---|
| `pillars/rejected.md` | "We **considered** this path and chose another." Past-tense alternative. |
| `pillars/non-goals.md` | "We deliberately are **not** building this." Scope guard. May never be built. |
| `pillars/backlog.md` | "We **will** build this, just **later**." Roadmap forward to a known future milestone. |

If you can't tell where a new item belongs, ask: *"Is the plan to build this eventually?"* Yes → `backlog.md`. No but circumstances could change → `non-goals.md`. We already weighed it against an alternative → `rejected.md`.

**Plan docs (`01-foo.md`, `02-bar.md`, ...) live at the top level** alongside the optional folders. Each owns one domain.

---

## Modes

The session has three modes. The mode is tracked in `state.md` (`MODE: explore | decide | step-back`) and gates the skill's behavior on every turn.

| Mode | Voice | Tool-use | When it applies |
|---|---|---|---|
| **explore** (default) | Facilitator + Scribe | No `AskUserQuestion` for picking options. Prose conversation. Pillar writes capture user-stated concerns in user's framing. | After intake, and any time the user signals they want to think rather than decide. |
| **decide** | Sparring partner + Architect-mentor (opt-in) | `AskUserQuestion` allowed when the user has explicitly invoked a resolution flow. Decisions written as `STATUS: tentative`. Cascades suppressed. | User signals: "let's resolve Q-N", "I want to decide X", "let's lock down Y". |
| **step-back** | Critic | Read-only across pillars. Present cumulative effect of decisions; offer rescind/commit on tentative items. | User signals: "step back", "review where we are", "what have we decided", "is this going the right direction". |

### Mode transitions

The mode changes only on **explicit user signal**, not on skill judgment. Read the user's words; do not infer mode shifts from topic shifts.

- **explore → decide**: user says "decide X" / "resolve Q-N" / "let's pick" / "lock this in" / similar. Write `MODE: decide` and the in-flight question to `state.md`. Stay in decide only as long as the active resolution requires; revert to explore the moment the resolution ends (committed, tentatively-written, or abandoned).
- **decide → explore**: user says "park this" / "let's just talk" / "explore mode" / "actually I don't want to decide yet" / similar. Or: the resolution flow naturally ends.
- **any → step-back**: user says "step back" / "review" / "let me see where we are" / "is this overall direction right" / similar.
- **step-back → explore or decide**: user signals what to do next after reviewing.

When entering a mode, **announce the shift** in one line — naming the topic in plain English, not by code — e.g., *"Switching to decide mode to settle whether a user-type can change answer depth. Stop me with 'park' if you want to keep thinking."* This makes the mode change observable.

### Behavior in explore mode (the default)

This is where the skill spends most of its time. The shape:

- **Listen first.** When the user names a concern, capture it as a `pillars/questions.md` entry in *their* framing. Repeat what you heard back in writing; don't restructure into a multi-option choice unless they ask.
- **No proactive recommendations.** Do not emit `Claude's take:` on questions, do not suggest "option A vs B", do not push toward resolution. The Architect-mentor voice activates only when the user asks something like "what should I be considering here?" or "what do you recommend?"
- **No `AskUserQuestion` for picking options.** Prose. If you need a clarification, ask in plain text. `AskUserQuestion` is reserved for intake (Step 1, Step 4) and explicit decide-mode resolutions.
- **Don't extract questions unprompted from source material.** If `./plan/sources/` has a draft doc, do not generate a list of questions from it on first read. Wait for the user to point at something or name a concern.
- **Mirror, summarize, capture.** When the user thinks out loud, paraphrase back, ask clarifying questions, and offer to write the result into a pillar. The user picks whether to capture.
- **Pillar-reinforcement prompts at topic shifts** still apply (see below) — those are conversational, not directive.

### Behavior in decide mode

User has signaled they want to resolve something. Even here, the skill is not in a hurry.

1. **Confirm the scope.** Restate the question in plain English (not "we're resolving Q-N"): "We're settling [the actual question, in your words]. Talk through it first, or go straight to picking options?" Prose response.
2. **If talk-through:** discuss the question + tradeoffs in prose. Pull in references, prior art, related decisions. Don't push toward picking. The user signals readiness ("OK, let's pick" / "I'll go with B" / "I've decided").
3. **If pick-now:** use `AskUserQuestion` with the options as written in `pillars/questions.md`. **Do not pre-lean an answer** unless the user already stated their pick in chat (in which case present it pre-leaned with a confirm step).
4. **Sparring once.** If the user picks something with weak rationale, push back once: name the unstated tradeoff. If they hold firm, accept. Don't push twice.
5. **Write the decision as `STATUS: tentative`** in `pillars/decisions.md`. Do NOT delete the question from `pillars/questions.md` yet — keep it in a "tentatively answered" state. Do NOT dispatch a cascade.
6. **Return to explore mode** after the write. State the mode shift. The decision sits as tentative until the user commits or rescinds.

### Behavior in step-back mode

User wants to see the cumulative effect of what's been decided.

1. Read all decisions in `pillars/decisions.md` in chronological order.
2. Group by milestone (M0, M1, M2, ...) and by status (committed / tentative / rescinded).
3. Present:
   - Cumulative scope of each milestone (compared to the original goal if captured in `pillars/milestones.md`).
   - Decisions that depend on or amend other decisions (chain reactions).
   - Tentative decisions awaiting commit.
   - Any contradictions or smell-words (see `greenfield.md`).
4. Ask in prose: *"Anything to reverse? Anything tentative to commit? Or back to explore?"*
5. User can rescind decisions, commit tentative ones, or return to explore mode. Do not transition out of step-back until the user signals.

---

## Tentative vs committed decisions

This is what gives the user breathing room. New decisions land as **tentative** by default. They are visible, they are real, but their downstream effects do not fire until the user commits.

### State machine

```
                  resolution flow
                       │
                       ▼
                  ┌─────────┐
                  │tentative│  ← new decisions land here
                  └────┬────┘
            user says   │   user says
            "commit"    │   "rescind"
                  ┌─────┴─────┐
                  ▼           ▼
            ┌─────────┐  ┌──────────┐
            │committed│  │ rescinded│
            └─────────┘  └──────────┘
```

### What's different between tentative and committed

| | Tentative | Committed |
|---|---|---|
| Visible in `decisions.md` | Yes | Yes |
| Question deleted from `questions.md` | No (still listed) | Yes |
| Cascade audit dispatched | No | Yes |
| Other pillars reference this decision | Allowed (just don't apply mechanical ripples) | Yes, fully |
| User can reverse easily | Yes, just rescind | Yes, but requires cascade reversal |

### Commit flow

User says "commit D-N" or "commit all tentative" or "commit the recent ones":

1. Read the named decision(s) from `pillars/decisions.md`.
2. Change `STATUS:` from `tentative` to `committed`. Record `**Committed on.** YYYY-MM-DD`.
3. Delete the resolved question from `pillars/questions.md`.
4. Dispatch the cascade audit (see "Live pillar realignment" below).
5. Return to explore mode.

### Rescind flow

User says "rescind D-N" / "undo D-N" / "actually I want to reverse that":

1. Read D-N from `pillars/decisions.md`.
2. **If `STATUS: tentative`** — the easy case:
   - Change `STATUS:` to `rescinded`. Record `**Rescinded on.** YYYY-MM-DD with reason "<one-line>"`.
   - The question never left `questions.md`, so nothing to restore there.
   - No cascade was ever dispatched, so no ripples to undo.
   - State: "D-N rescinded. The original question is still open in `pillars/questions.md`."
3. **If `STATUS: committed`** — harder:
   - Read the cascade-ripples that fired for this decision. Search the brainstorm folder for references to `D-N` and identify the mechanical edits the cascade applied (the cascade reports its applied items in your conversation history; if you cannot reconstruct, ask the user which ripples to reverse).
   - Present the reversal punch list to the user. Wait for approval per item.
   - Apply reversals.
   - Restore the original question to `questions.md` from D-N's "Resolves Q-N" reference + the alternatives that were offered.
   - Mark D-N as `STATUS: rescinded`.
   - Flag any *downstream* decisions that referenced D-N as potentially needing review.

Rescinded decisions stay in `pillars/decisions.md` as historical record. They are one of the four places where past tense is allowed (the others: live `decisions.md` entries, `rejected.md`, `references.md`).

---

## `start` — opening a session

### Step 1. Qualification (Facilitator voice)

Before doing anything else, ask 2–4 qualifying questions via `AskUserQuestion`. This is one of the few legitimate uses of `AskUserQuestion` — scope clarification:

- **What are you designing?** (new system / new feature on an unbuilt system / migration / refactor / something smaller)
- **What's built so far?** (nothing / scaffolding only / partial / mostly done)
- **What's the rough scope?** (single service / multi-service / cross-team / one-day spike)
- **Is the goal to lock decisions before code, or something else?**

If the answers indicate the skill is a **poor fit** — debugging an existing bug, writing a one-day script, adding a single button, fixing a typo, working in an established codebase that doesn't need design — say so explicitly:

> "This skill is for structured design of unbuilt systems. Your problem sounds more like [X] — [other skill / direct action] would fit better. Want me to dump the conversation so far into a markdown file you can pick up there? Or, if you still want to run a brainstorm here, say so and I'll continue."

**Do not exit unilaterally.** The user decides.

### Step 2. Folder selection

Decide where the session lives. **Detect first, ask only if ambiguous.**

1. Scan the working directory for candidate folders:
   - Conventional names: `./plan/`, `./brainstorm/`, `./design/`.
   - Any other folder containing `state.md` plus a `pillars/` subfolder. Limit the scan to one level deep.
   - **Backward compatibility:** if you find a folder with `state.md` at top level AND pillar files at top level (pre-`pillars/` layout), treat it as a legacy session and continue working in that layout.
2. Resolve:
   - **Exactly one candidate** → confirm in a single line: *"Resuming in `./<folder>/` — OK?"* Default yes.
   - **Multiple candidates** → present them via `AskUserQuestion`, plus "Other" for a custom path.
   - **None found** → ask via `AskUserQuestion`: propose `./plan/`, `./brainstorm/`, `./design/`, or "Other".
3. **Anchor the session to the chosen folder.** From this point on, every reference in this document to `./plan/` resolves to the folder selected here.

If the chosen folder doesn't exist yet, it's created during Step 3 along with the pillar bootstrap.

### Step 3. Bootstrap if needed

If the session folder doesn't have `pillars/` populated, copy templates from this skill's templates directory into `<folder>/pillars/`. Skip any file that already exists — never overwrite.

```bash
mkdir -p <folder>/pillars
cp <skill-dir>/templates/{questions,decisions,doctrine,glossary,inventory,non-goals,references,rejected,milestones,backlog}.md <folder>/pillars/
```

Write `state.md` at the **top level** (overwriting is OK):
```
STATE: open
MODE: explore
SESSION STARTED: <ISO date>
CURRENT TOPIC: <one-line summary from intake>
LAST UPDATED: <ISO date>
```

### Step 3.5. Source materials (optional)

A brainstorm is rarely a blank slate. Before intake, ask in prose:

> "Are there existing documents or projects whose technical design you want to improve in this session? If yes, point me at paths or URLs and I'll copy them into `./plan/sources/` so we don't have to re-read from their original locations."

If yes:
- Create `./plan/sources/` and copy each file in (or `WebFetch` if URL → save as markdown).
- Write `./plan/sources/README.md` with a single line: `delete after brainstorm is over`.
- Add an entry to `pillars/references.md` for each source pointing at `./plan/sources/<filename>` with a one-line note on what it's for.

**Important:** copying a source into `sources/` does **not** authorize you to extract questions from it. Source material is reference, not a question-generation prompt. Wait for the user to point at concerns inside the source.

### Step 4. Intake interview (Facilitator voice, `AskUserQuestion` for scope only)

Use `AskUserQuestion` in topical bundles (2–4 questions per batch) **only for genuine scope clarifications**:

- What's the system for, who uses it, what does it ship? → seeds `pillars/inventory.md` + `pillars/milestones.md` M0 goal
- What are you explicitly NOT building? → seeds `pillars/non-goals.md`
- What's next-phase work you already know about but aren't building now? → seeds `pillars/backlog.md`
- Any reference implementations or prior art you already know? → seeds `pillars/references.md`
- Any hard constraints (cloud, language, deploy target, vendor preferences)? → seeds `pillars/doctrine.md`

**Note what is NOT in this list:** "What are the obvious open questions?" That seeding belongs in explore mode, driven by the user's actual concerns, not extracted by the skill.

Write each answer directly to the relevant pillar as it comes in. Don't accumulate in conversation then dump at the end.

### Step 5. First-pass review (Facilitator voice)

Once intake is seeded, show the user:
- The list of pillars with one-line summaries of what was captured in each.
- A note that `pillars/questions.md` is empty (and that's fine — questions enter as the user names them).

Then ask, in prose (no `AskUserQuestion`):

> "What would you like to explore? You can name a topic you're worried about, name a concern, point at something in a source doc, ask me to talk through something, or step back if anything captured so far feels off."

The session is now in **Explore mode**. Resolution-style flows are opt-in from here. The skill is reactive — it captures what the user surfaces, and only proposes when invited.

---

## `stop` — stopping a session

0. **Drain in-flight cascades.** Read `state.md`'s `CASCADE LOCKS` section. If any locks are active, wait for the corresponding sub-agents to finish before proceeding. Drain the `CASCADE QUEUE` too. Goal: no half-applied cascades when the session closes.

1. Read all pillars (`pillars/*.md`) and plan docs (numbered docs at the top level).

2. Run gap detection:
   - Greenfield smell-words grep across plan docs and pillar docs (see `greenfield.md`).
   - Decisions in `pillars/decisions.md` with `STATUS: tentative` — these are uncommitted; the user should commit or rescind before closing.
   - Decisions missing **Why** or **How to apply**.
   - Questions in `pillars/questions.md` with no `Blocks.` field.
   - Pillars that haven't been touched since `start`.
   - Plan docs with their own "Open Questions" section instead of a pointer to `pillars/questions.md`.
   - Versioned plan-doc drafts (`*-v0.X.md`) where the latest version isn't marked stable.
   - Items in `pillars/non-goals.md` that look like deferred-but-planned work (have a concrete target milestone in their re-evaluate clause) — these belong in `pillars/backlog.md`.
   - Items in `pillars/backlog.md` with no **Target milestone** field.

3. Report gaps; do not auto-fix.

4. Ask the user if they want to address gaps now or stop anyway. Tentative decisions in particular: surface them and ask "commit / rescind / leave as tentative for resume?"

5. On confirmation, write `STATE: closed` to `state.md` with a one-line reason (milestone reached / paused / scope cut / handing off). Keep the `MODE:` field at its last value for resume.

6. **If `./plan/sources/` exists,** offer to delete it (per its README marker). Default to keep if unclear.

7. **If versioned plan-doc drafts exist,** offer to prune older drafts. Default to keep.

8. Print: "Run `/technical-brainstorm start` to resume."

---

## In-session behavior

### Speak English in the conversation; codes live in the files

The pillar codes — `Q3`, `D7`, `P2`, `M1`, `R1` — are addressing labels for the **files**, where they enable stable, self-contained cross-references. They are **not** a language for talking to the user.

When you write to the user in the conversation, assume they are **not** looking at the pillar files. They are in a terminal, talking to you. A message like *"Q6a is still open; D3 tentatively answers Q1 but conflicts with P3"* is unreadable to someone who isn't staring at `questions.md` and `decisions.md` — it forces them to stop, open files, and search for each code. That is the opposite of a conversation, and it is a real failure even if every code is technically correct.

**The rule:** in every user-facing message, refer to a pillar item by **what it is** — a few plain words — not by its code alone.

- ❌ "Q6a is the last residual before we can commit D1–D3."
- ✅ "One open thread before we lock these in: can a user-type change *how deep* an answer goes, or only its tone?"
- ❌ "This conflicts with P3 and re-opens R1."
- ✅ "This clashes with our read-only-agent principle, and it risks reviving the audience-altitude idea we already threw out."

If you genuinely need the code for traceability, **append it in parentheses after the plain-English statement** — never lead with it, never use it alone:

- ✅ "…can a user-type tune answer *depth*? (open question, tracked as Q6a)"

This holds for questions, decisions, doctrine, milestones, rejected items — every coded entry, and for lists of them too: don't hand the user a table of bare codes to go decode. The files stay terse and code-cross-referenced; the conversation stays human. The user should never have to open a pillar file to understand what you just said.

### Voices, by mode

| Mode | Default voice | When voice shifts |
|---|---|---|
| Intake | Facilitator | Always |
| **Explore** (default) | Facilitator + Scribe | Architect-mentor only when user explicitly asks "what should I consider?" / "any prior art?" / "what would you recommend?" |
| **Decide** | Sparring partner | Architect-mentor when surfacing tradeoffs the user hasn't named |
| **Step-back** | Critic | The whole mode |
| `stop` and gap detection | Critic | Always |

Voice shifts happen only on explicit signal from the user. The skill does not pre-emptively switch into Architect-mentor or Sparring-partner. If the user is just talking through a worry, you listen; you don't offer alternatives unless asked.

### Writing recommendations on open questions

The `Claude's take:` field in `pillars/questions.md` is **opt-in**.

- **Default: do not write it.** Capture the question, options (if the user named them), and lean (if the user has one). Stop there.
- **Emit only when asked.** When the user says "what's your take?" / "what would you recommend?" / "if you had to pick" / similar, write a one-line take. Mark it as a separate paragraph; never inline with the user's framing.
- **Stale takes:** if the question changes shape (new option added, scope shifts), delete the existing take. Don't leave a stale recommendation.

`Claude's take:` is not the same as the in-conversation Sparring-partner pushback during decide mode — that's verbal. The field is a written artifact and exists only when asked.

### Capturing user concerns as questions (Explore mode)

The most important capture flow. When the user says something like *"I'm worried about how Bluetooth headphones break the experience"* or *"I don't know what the right way to handle X is"*:

1. **Mirror it back.** "Sounds like the concern is [restated in your words] — is that right?"
2. **Offer to capture.** "Want me to add this as an open question?"
3. **If yes**, write it to `pillars/questions.md` in the user's framing:
   ```
   ## Q-N — [Title in user's words]

   **Question.** [Full prose — paraphrase what the user said, not what you would have asked.]

   **Resolution lands in.** [Plan doc + section if known, otherwise leave blank.]

   **Blocks.** [Milestone if known, otherwise leave blank.]
   ```
   Do **not** generate Options, Lean, or Claude's take fields at capture time. Those land later if/when the user moves the question into decide mode.

4. **Stay in explore.** Don't pivot to "shall we resolve this now?" — the user will say so when ready.

### When the user shifts topics — pillar reinforcement

When the conversation moves from one design topic to another (e.g., "OK we're done thinking about auth, let's talk about the event bus"), pause **before** entering the new topic:

> "I see we're moving from [previous topic] to [next topic]. Before we shift — looking at what we just covered, do any of these belong in the load-bearing pillars?
> - [Candidate 1] → could go in `pillars/glossary.md` because [reason]
> - [Candidate 2] → could go in `pillars/doctrine.md` because [reason]
> - [Candidate 3] → could go in `pillars/rejected.md` because [reason]
> - [Candidate 4] → could go in `pillars/backlog.md` because [reason]
>
> Promote any of them?"

The user picks what to promote. Update the named pillars, then update `state.md`'s `CURRENT TOPIC` field. Then proceed with the new topic.

This is the **only** periodic prompt. There is no scheduled "checkpoint" or "review" — pillar reinforcement happens at natural topic boundaries because that's when the closing context is fresh.

### Live pillar realignment (background cascade) — only on commit

A brainstorm session that lets pillars drift between committed decisions accumulates stale entries. The cascade mechanism keeps the brainstorm folder consistent **between** decisions instead of catching up at the end.

**Critical change from older versions of this skill:** cascades fire **only on `STATUS: committed` decisions**, not on `tentative` ones. New decisions land tentative; cascade dispatch is part of the commit flow, not the write flow.

**The cascade mechanism.** When a decision transitions to committed (or when another load-bearing pillar is directly written: `doctrine.md`, `rejected.md`, `non-goals.md`, `milestones.md`, or a plan doc), the skill **dispatches a read-only sub-agent in the background** to audit cascading impact on other pillars and plan docs. The sub-agent produces a punch list of follow-on edits. The main agent keeps talking to the user. When the sub-agent reports back, the main agent applies the mechanical items silently and surfaces the judgment items at the next natural turn break.

**What triggers a cascade:**

| Event | Triggers cascade |
|---|---|
| Decision committed (STATUS: tentative → committed) | Yes |
| Direct write to `pillars/doctrine.md` | Yes |
| Direct write to `pillars/rejected.md` | Yes |
| Direct write to `pillars/non-goals.md` | Yes |
| Direct write to `pillars/milestones.md` | Yes |
| Plan-doc write (`NN-*.md`) | Yes |
| Tentative decision written | **No** |
| `questions.md` / `glossary.md` / `inventory.md` / `references.md` / `backlog.md` write | **No** (downstream pillars; ripple captured by their source decision) |
| `state.md` / `sources/*` / `samples/*` | No (administrative) |

**The cascade sub-agent.** Dispatched via `Agent` tool with `subagent_type: "general-purpose"` and `run_in_background: true`. The prompt template:

> Brainstorm cascade audit for folder `<brainstorm-folder>`.
>
> A change just landed at `<changed-file>`. The new content (full text or relevant section) is below. Your job: audit all OTHER pillars and plan docs in the brainstorm folder for follow-on edits this change requires.
>
> Check:
> - `pillars/rejected.md` — does any rejected entry need a "Partially superseded by <decision-id>" annotation?
> - `pillars/non-goals.md` — does any non-goal item have a re-evaluate trigger that this change fired?
> - `pillars/doctrine.md` — does this change reverse, amend, or supersede any doctrine entry?
> - `pillars/inventory.md` — does the change introduce new artifacts that need cataloguing?
> - `pillars/backlog.md` — does the change defer something that needs a new backlog entry with target milestone?
> - `pillars/glossary.md` — does the change introduce or rename terms that need definition?
> - `pillars/references.md` — does the change cite new external sources?
> - `pillars/milestones.md` — does the change affect milestone scope, dependencies, or open-question lists?
> - Plan docs (`NN-*.md`) — does the change contradict, supersede, or extend a plan-doc section?
>
> Output a structured punch list. For each file needing an edit: file path / section / type (ANNOTATE / DELETE / AMEND / EXTEND / NEW-ENTRY) / category (MECHANICAL — auto-applicable from the source change's How-to-apply field; or JUDGMENT — needs user input) / proposed new text (for MECHANICAL) OR question (for JUDGMENT).
>
> Do NOT make edits. Read-only audit. Report under 400 words.

**Race condition guard.** Each cascade lock is keyed by **source pillar file**. Before dispatching a cascade for source `<file>`, check `state.md` for an active `CASCADE LOCK`:

- **No active lock** → dispatch immediately; write a `CASCADE LOCK` entry to `state.md`.
- **Active lock for the same source** → do NOT dispatch. Append to `CASCADE QUEUE`. Drain when the active lock clears.
- **Active lock on a different source** → fine, dispatch concurrently.

**Integration of cascade output.** When a sub-agent finishes:

1. Read the punch list.
2. **MECHANICAL items** — apply directly. Note silent application in the next user-facing message: *"Cascade applied: rejected.md R1/R2/R7 annotated; non-goals.md 3 entries deleted."*
3. **JUDGMENT items** — surface to user: *"Cascade audit found 2 items needing your call: [item 1], [item 2]. Apply now or defer?"*
4. Remove the lock from `state.md`. Drain any queued cascade for the same source pillar.

**Stale lock detection.** A cascade sub-agent that takes longer than 5 minutes is presumed stuck. Surface to the user and clear on confirmation.

---

### When the user asks to "update the docs" / "propagate this"

Run a **semantic sweep**, not a grep:

1. List all numbered plan docs and any pillar files that might be affected.
2. Read each end-to-end, looking for sections that reference the just-changed concept.
3. Present a punch list grouped by file: file → section → proposed edit.
4. Wait for approval before editing.

Sweeps are **never automatic**. They are user-requested.

### Plan-doc versioning (preserving evolution)

Plan docs (`01-foo.md`, `02-bar.md`, ...) sometimes go through substantial rewrites mid-session. **Preserve the evolution** by using version suffixes rather than overwriting in place:

```
01-architecture-v0.1.md            ← initial draft
01-architecture-v0.2.md            ← second draft after a big decision change
01-architecture-v0.3.md            ← current draft
```

**When to version:**
- A major decision reversal forces a structural rewrite.
- ≥3 sections of the plan doc need synchronized changes that don't fit neatly in targeted edits.
- The user explicitly asks for a "v0.X" or "next draft".

**When NOT to version (just edit in place):**
- Typo, paragraph polish, single-section update, adding a missing detail.
- Renaming a variable / consistent find-and-replace across the doc.
- Small additions that don't change the doc's structural shape.

**Numbering scheme:**
- The leading number (`01-`, `02-`, ...) identifies the **domain**. Same domain across versions.
- The `v0.X` suffix identifies the **draft iteration**.

Plan-doc evolution is in addition to the pillar files. Pillars are append-only ledgers; plan docs may go through visible drafting iterations.

### When the user asks for code

The skill **refuses to write production code** outside the brainstorm folder while a session is open. This includes source files in `src/`, `apps/`, `packages/`, or any code directory the project owns.

**Carve-out:** small load-bearing snippets that anchor a design decision are allowed **inside the brainstorm folder** as illustration. Put them in `./plan/samples/` or inline in the relevant plan doc as fenced code blocks. They are documentation, not production.

If the user asks for production code, say:

> "We're in an active brainstorm session. I can sketch this inside `./plan/` as illustration, or you can run `/technical-brainstorm stop` first if you want to start building. Which do you want?"

---

## Hard rules

These hold for the entire session.

1. **No production code outside the brainstorm folder.** Small load-bearing snippets go in `./plan/samples/` or inline in plan docs. Never touch `src/`, `apps/`, `packages/`.
2. **Resolved (committed) questions get DELETED, not struck through.** No `~~`, no "(resolved)", no "previously planned". Tentative questions stay in `questions.md` until commit.
3. **Self-contained registry.** Full text in `pillars/questions.md`. Never `08 §5` cross-references.
4. **Every decision carries Why + How to apply.** Without the *why*, future-you can't judge edge cases.
5. **Reference implementations beat invented solutions.** If prior art exists, link in `pillars/references.md` and use it. Don't re-derive.
6. **`AskUserQuestion` is for explicit decide-mode flows and intake-scope clarifications only.** In explore mode, use prose. Never bundle structured options into `AskUserQuestion` when the user is exploring, not deciding.
7. **Greenfield writing rules apply** to all docs in the brainstorm folder. See `greenfield.md`.
8. **No past tense for software that doesn't exist yet.** Architecture docs are present-tense. The past lives only in `pillars/decisions.md`, `pillars/rejected.md`, `pillars/references.md`, versioned older drafts, and git history.
9. **`state.md` stays at the top level.** Never move it into `pillars/`. It is the session-lifecycle + mode gate.
10. **Tentative decisions don't cascade.** Cascades fire on commit, not on tentative write. This gives the user reversible state.
11. **Mode shifts are user-initiated.** The skill does not transition explore → decide on its own judgment. The user must signal.
12. **Claude's take field is opt-in.** Default off. Only emit when the user asks for a recommendation on a specific question.
13. **Speak English to the user; codes are for files.** In conversation, name every pillar item by what it *is* (a few plain words), never by its bare code (`Q3`, `D7`, `P2`). Append the code in parentheses only when traceability needs it — never lead with it or use it alone. The user is not looking at the files. See "Speak English in the conversation; codes live in the files."

---

## State file

`state.md` is the source of truth for session lifecycle and mode. Read it at the start of every turn.

```
STATE: open | closed
MODE: explore | decide | step-back
SESSION STARTED: <ISO date>
SESSION CLOSED: <ISO date or absent>
CURRENT TOPIC: <one-line>
LAST UPDATED: <ISO date>
CASCADE LOCKS:
  - <source-pillar-file> (sub-agent <id>, started <ISO timestamp>)
CASCADE QUEUE:
  - <source-pillar-file> (queued at <ISO timestamp>)
```

- `STATE: open` → in-session behavior applies.
- `STATE: closed` → the skill does nothing on its own; `/technical-brainstorm start` re-opens it.
- `MODE:` gates voice and tool-use posture (see "Modes" section).
- Update `CURRENT TOPIC` on every detected topic shift.
- Update `LAST UPDATED` on every pillar write.
- `MODE` updates on every transition; announce the transition in the user-facing message.
- When `CASCADE LOCKS` and `CASCADE QUEUE` are empty, render them as `CASCADE LOCKS: none` and `CASCADE QUEUE: none`.

---

## The 10 pillars (+ plan docs)

All pillars live in `<session-folder>/pillars/`. Each template carries a full prose introduction. Read the template, not this table, when you need format details.

| File | One-line role |
|---|---|
| `pillars/questions.md` | Live ledger of unresolved concerns and pending decisions. User's framing, not the skill's. |
| `pillars/decisions.md` | Resolved decisions with **Status** (tentative / committed / rescinded), **Why**, **How to apply**. Append-only. |
| `pillars/doctrine.md` | Stable principles that pre-answer future questions. |
| `pillars/glossary.md` | Project-specific terms. |
| `pillars/inventory.md` | What exists / is being built / is external / is reference-only. |
| `pillars/non-goals.md` | Explicit "not building" list, each with a reason. May never be built. |
| `pillars/references.md` | External prior art with one-line "what we use it for". |
| `pillars/rejected.md` | Alternatives considered and rejected, with reasons + re-evaluate conditions. |
| `pillars/milestones.md` | Sequencing only. Each milestone names its blocking questions and dependencies. |
| `pillars/backlog.md` | Deferred-but-planned items. **Will** be built, just not now. |

Plus **plan docs** at the top level — `01-foo.md`, `02-bar.md`, ... — domain-by-domain architecture, present-tense.

---

## Greenfield doctrine

Loaded separately at `<skill-dir>/greenfield.md`. Read it before any sweep, gap detection, or stop — that's where the smell-words grep and the banned-patterns table live.
