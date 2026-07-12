---
name: brainstorm
description: Thinking-partner session for designing software. Invoked ONLY by explicit slash commands `/brainstorm start` and `/brainstorm stop` — never auto-invoke on natural-language phrases like "let's plan", "let's design", or "let's think through X". Entry requires a basis (a reference document or a one-shot brain dump); drip-fed action items are rejected as too small. Runs one constant loop (distill → abstract → sync → record) across four modes (dump / interview / probe / converge). Coherence = zero open questions after a fresh pillar sync. Pillar count scales with a complexity dial; refuses production code outside the session folder while open.
argument-hint: "start | stop"
plugins: [code]
---

# Brainstorm

Think with the user, then file — never the reverse. The artifacts exist to serve the conversation; the conversation never exists to populate artifacts. The constant across every scale of idea is **the loop**; everything else — pillar count, ceremony, harvest — scales with complexity.

## The loop — every turn, every mode

1. **Distill.** Fold what the user just said into the pillars, in *their* framing, during the same turn.
2. **Abstract.** Name the latent structure they implied but didn't state — entities and relationships ("an account has many leads" → `domain-model.md`), invariants, principles, terms. Offer at most one abstraction per exchange; it's a contribution, not a lecture.
3. **Sync.** Keep the pillars consistent with each other and with the basis (see **The sync agent**).
4. **Record.** Writes happen in the turn that produced the information — never accumulated for a session-end dump.

Modes change *who drives* and *how much gets asked*. The loop never stops.

## Modes

| Mode | Who drives | When | Behavior |
|---|---|---|---|
| **dump** | user | idea is in their head | No questions mid-stream. Distill live. After each chunk, reflect back: the shape, contradictions, implications. Distillation + reconciliation **is** active listening — never sit silent. |
| **interview** | skill | idea is fuzzy | Question batches of 2–3 via `AskUserQuestion`, scoped to **one aspect at a time**. Distill each answer immediately. Questions derive from the basis and the pillars — never from a template inventory. |
| **probe** | skill | idea is drafted, needs stress | Challenge it: flaws, edge cases, conflicts with `tech.md` / `doctrine.md` / the domain model. Each finding becomes a question (`Raised by: probe`) — file it and move on; don't demand resolution. |
| **converge** | shared | closing in | Burn down open questions. `AskUserQuestion` allowed for picks. Each resolution → a decision with **Why** + **How to apply**, or an explicit park (backlog / non-goals). Ends with a mandatory fresh sync. |

**Switching** is an explicit user word ("let me dump", "ask me questions", "poke holes", "let's converge"). On a strong signal — the user starts monologuing mid-interview, or answers every probe with "I haven't thought about it" — **offer** the switch in one line. Never seize it. Announce every shift in plain English: *"Switching to probe — I'll push on the sync-layer design. Say 'park' anytime."*

## `start`

### 1. The entry gate

A session needs substance before it opens. Ask for a **basis**: a reference document (path or URL), or a one-shot brain dump of the whole idea, right now, in prose.

- Basis arrives → copy/save it into `<folder>/basis/` and proceed.
- The user offers drip-sized input — a bug fix, a single button, small action items — say this skill is the wrong tool, recommend stopping, and **do not open the session** unless the user explicitly overrides.
- No basis and no dump → no session.

### 2. Read the basis, propose the frame

Distill the basis *first* — this seeds `thesis.md` and the initial questions. Then one `AskUserQuestion` batch:

- **Complexity** — low / medium / high. The skill proposes from the basis; the user confirms. This sets the default pillar surface (see **Pillars**) and ceremony depth.
- **Build mode** — "Is this greenfield, or are we changing something that exists?" (greenfield / brownfield / hybrid). The answer lands in `build.md` and opens or closes its execution sections — migration strategy and gotchas are brainstorm-phase concerns; surfacing them in plan mode is too late.
- **Mode** — "Where is this idea right now — fully in your head (dump it), half-formed (I'll interview), or drafted and needing stress (I'll probe)?"

Then propose the **aspect map**: the thinking dimensions for *this specific idea* (e.g., for a product: users/jobs, domain model, architecture, tech, risks; for a small tool: behavior, interface, failure modes). Derive it from the basis — there is no fixed list. The user edits it; write it into `thesis.md`. The map is the coverage source for the sync audit.

### 3. Bootstrap

Session folder: `./brainstorm/` by default (or `./plan/`, `./design/`, custom — reuse any folder containing `state.md`; confirm in one line). Create only the pillars the complexity calls for, from `templates/` (never overwrite existing files; if a template is missing, create the file from the field lists in **Pillars**). Write top-level `state.md`:

```
STATE: open
MODE: dump | interview | probe | converge
COMPLEXITY: low | medium | high
SESSION STARTED: <ISO date>
CURRENT TOPIC: <one line>
LAST SYNC: <ISO datetime or never>
SYNC IN FLIGHT: no
```

Initial questions come from the basis distillation **only** — contradictions in the dump, gaps the aspect map exposes. Never interview to fill empty templates.

## Pillars — substance first, lazy by default

| Pillar | Holds | Exists |
|---|---|---|
| `thesis.md` | What we're designing — running narrative, kept current + the aspect map | always |
| `questions.md` | The **single convergence currency** — every unresolved design call, whoever raised it | always |
| `decisions.md` | Resolved calls with **Why** + **How to apply** | always |
| `build.md` | How the work gets executed: build mode (greenfield default / brownfield / hybrid), migration strategy, gotchas, rollout. Greenfield closes the execution sections; brownfield opens them | always |
| `domain-model.md` | Entities, relationships, cardinalities, state ownership | medium+ |
| `tech.md` | Stack choices, seeded from harness rules (e.g. `.claude/rules/general.md`) at bootstrap; deviations recorded with whys | medium+ |
| `doctrine` / `glossary` / `non-goals` / `backlog` / `rejected` / `references` / `milestones` | as their templates describe | **lazy** — materialize on first real content, any complexity |

The complexity dial sets *defaults*, not a cage: any lazy pillar materializes mid-session the moment the conversation produces content for it, and at **low** complexity the always-four may even live as sections of a single file if the user prefers.

**Question entries** (`questions.md`): self-contained full prose in the user's framing, plus —

- **Raised by.** user | sync | probe
- **Closes when.** What resolution looks like — a pick, a confirmed fact, an accepted risk. Every question must be closeable.
- **Options / Lean / Claude's take** — optional; *Claude's take* remains opt-in (only when the user asks for a recommendation).

**Decision entries** (`decisions.md`): append-only; **Decision**, **Why**, **How to apply**, **Resolves Q-N**. There is no tentative/committed state machine. Reversing a decision = append a new decision that names what it reverses, mark the old entry "Reversed by D-M", and let the next sync handle the ripples.

## The sync agent

The background reconciler that replaces ceremony with consistency. **One sync in flight at a time; queue at most one behind it.**

**When:** after a distillation batch lands substantive pillar writes (at the turn break, not mid-sentence); mandatorily on entering converge and at `stop`; on demand. At **low** complexity, run it inline yourself; at **medium+**, dispatch a background `general-purpose` agent (read/write access to the session folder only).

**Contract — audit exactly four sources:**

1. **Cross-pillar contradiction** — thesis vs domain model vs decisions vs doctrine vs build (a decision that implies migration work with no `build.md` entry is a contradiction).
2. **Aspect coverage** — any aspect on the map with no content anywhere → emit a question.
3. **Basis drift** — does the thesis still agree with `basis/`? Divergence is fine if decided; accidental divergence → emit a question.
4. **Tech conflicts** — anything that violates `tech.md` without a recorded deviation.

**Output:** direct pillar edits for **scribe-calls**, new questions for **design-calls**, and a one-line report.

**The line:** a *scribe-call* is anything whose resolution doesn't change the design — wording, annotations, obvious bookkeeping. Just do it; list it in the report (the user can veto). A *design-call* is anything whose resolution changes the idea — file it as a question (`Raised by: sync`) and move on. **Never** interrupt the conversation to ask "apply now or defer?" — file and continue.

**The report is the status line.** Deliver it at the next natural turn break:

> Sync: 4 edits applied · 2 new questions · **6 open** · untouched aspects: risks

There is no separate dashboard, no scheduled checkpoint. This line is the only ambient convergence pressure the skill applies.

## Coherence

```
coherent ⇔ open_questions == 0 ∧ last sync ran after the last pillar write
```

Zero means *"audited against the four sources and clean"* — never *"nothing came to mind."* Don't declare the idea coherent on any other basis. Distance-to-coherent is always visible in the sync report; the **user** decides when to converge and when to close. The skill never says "let's decide now."

## `stop`

1. Run a final sync (wait for any in-flight sync first).
2. **Coherent** → say so and proceed. **Questions open** → list them plainly (English first, codes in parentheses) and offer per question: resolve now (mini-converge) / park explicitly (backlog or non-goals, with reason) / leave open and stop anyway — the folder keeps full state and resumes exactly where it left off.
3. **Harvest** — see `harvest.md`. Standalone by default: the session folder *is* the product. If the repo is v9-harnessed (`docs/architecture/` + `docs/modules/` exist), offer the adapter routing; never assume it.
4. Write `STATE: closed` + one-line reason. Print: *"Run `/brainstorm start` to resume."*

## Conduct — holds for the whole session

1. **Speak English; codes live in files.** In conversation, name every pillar item by what it *is* in plain words. Append the code in parentheses only when traceability needs it (*"…can a user change answer depth? (tracked as Q6)"*). Never lead with a bare `Q3`/`D7`. The user is not looking at the files.
2. **No production code outside the session folder.** Illustrative load-bearing snippets are fine inside it (`samples/` or fenced in pillars). If asked for production code: offer a sketch inside the folder, or `/brainstorm stop` first.
3. **The writing posture comes from `build.md`'s mode.** Greenfield: every pillar describes the system as it *will be*, present tense, as though the chosen design was always the plan — no migration vocabulary, no phantom history (banned list in `templates/build.md`). Brownfield/hybrid: migration vocabulary is legitimate, and `build.md` is its home; other pillars still describe the *target* state.
4. **`AskUserQuestion` appears in exactly three places:** the intake frame batch, interview mode, and converge picks. Everywhere else: prose.
5. **Suggested, never seized.** Mode shifts, abstractions, probes — one offer each, accept refusal without re-litigating.
6. **Questions are the only convergence currency.** Flaws, gaps, contradictions, uncovered aspects — everything unresolved funnels into `questions.md` or it doesn't exist. Nothing pending may live only in the conversation transcript.
7. **No auto-invocation.** Only `/brainstorm start` and `/brainstorm stop` enter or leave a session. Read `state.md` at the start of every turn while a session folder exists.
