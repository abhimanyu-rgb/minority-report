# brainstorm

A Claude Code skill that is a **thinking partner for designing software** — not a form to fill in. It runs one constant loop (distill → abstract → sync → record) over a conversation, files the thinking into a small set of substance-first pillars, and treats *coherence* as a measurable target rather than a vibe.

The point of v2 is a single inversion over v1: **the conversation is the work; the artifacts serve it.** v1 had grown into elaborate bookkeeping (a tentative/committed decision state machine, background cascade locks and queues, a 10-pillar eager bootstrap, an unconditional greenfield doctrine) wrapped around thinking that never had to happen. v2 deletes that machinery and keeps the loop.

---

## The loop (the only constant)

Every turn, in every mode:

1. **Distill** — fold what the user said into the pillars, in their framing, this turn.
2. **Abstract** — name the latent structure they implied but didn't state (an entity relationship, an invariant, a principle). One offer per exchange.
3. **Sync** — keep the pillars consistent with each other and with the basis (the sync agent, below).
4. **Record** — writes happen in the turn that produced the information; nothing is hoarded for a session-end dump.

Everything else — pillar count, ceremony, harvest — scales with the idea. The loop does not.

---

## Lifecycle

Two subcommands, nothing else. The skill never auto-invokes on natural language.

```
/brainstorm start    # open a session (requires a basis)
/brainstorm stop     # close a session
```

### The entry gate

A session needs substance before it opens. `start` asks for a **basis**: a reference document, or a one-shot brain dump of the whole idea. If the user drip-feeds small action items (a bug fix, a single button), the skill says it's the wrong tool and **does not open** unless overridden. The basis *is* the first dump — the skill distills it into the initial thesis and questions, so the first questions come from the user's own material, never from an empty template.

### Intake frame

After distilling the basis, one `AskUserQuestion` batch sets three dials:

- **Complexity** (low / medium / high) — sets the default pillar surface.
- **Build mode** (greenfield / brownfield / hybrid) — lands in `build.md`; opens or closes the execution sections and sets the writing posture.
- **Mode** — where the idea lives right now (see below).

Then the skill proposes an **aspect map** — the thinking dimensions for *this* idea — which the user edits. The map drives the sync's coverage audit.

### Modes (who drives)

| Mode | Driver | When | Behavior |
|---|---|---|---|
| **dump** | user | idea is in their head | No questions mid-stream. Distill live, reflect back shape + contradictions + implications. |
| **interview** | skill | idea is fuzzy | Question batches of 2–3, one aspect at a time, each answer distilled immediately. |
| **probe** | skill | idea is drafted | Adversarial pass — flaws, edge cases, conflicts. Each finding becomes a question. |
| **converge** | shared | closing | Burn down open questions into decisions or explicit parks; ends with a mandatory sync. |

Mode switches on an explicit user word. On a strong signal the skill *offers* a switch in one line; it never seizes it.

---

## Coherence (the doneness function)

```
coherent ⇔ open_questions == 0 ∧ last sync ran after the last pillar write
```

`questions.md` is the **single convergence currency**: flaws, gaps, contradictions, and uncovered aspects all funnel into it, whoever raised them. Convergence is one number going to zero. Zero means *"audited against the four sources and clean,"* never *"nothing came to mind"* — which is why the sync agent's audit contract is mandatory.

---

## The sync agent

The background reconciler that replaces v1's cascade apparatus. One sync in flight at a time; at most one queued behind it. It runs after substantive writes, mandatorily on entering converge and at `stop`, and on demand. It audits exactly four sources:

1. **Cross-pillar contradiction** — thesis vs domain model vs decisions vs doctrine vs build.
2. **Aspect coverage** — any mapped aspect with no content → a question.
3. **Basis drift** — does the thesis still agree with the basis? Accidental divergence → a question.
4. **Tech conflicts** — anything violating `tech.md` without a recorded deviation.

It applies **scribe-calls** (edits that don't change the design) directly and notes them; it files **design-calls** (edits that change the idea) as questions and moves on — never interrupting to ask "apply now or defer?" Its one-line report ("4 edits · 2 new questions · 6 open · untouched: risks") is the only ambient convergence pressure the skill applies.

---

## Pillars (substance first, lazy by default)

Always present: `thesis.md`, `questions.md`, `decisions.md`, `build.md`. Materialized at medium+ complexity: `domain-model.md`, `tech.md`. Lazy (materialize on first real content at any complexity): `doctrine`, `glossary`, `non-goals`, `backlog`, `rejected`, `references`, `milestones`.

| File | Role |
|---|---|
| `thesis.md` | Running narrative of what we're designing + the aspect map. |
| `questions.md` | Single convergence currency — every unresolved design call. |
| `decisions.md` | Resolved calls with **Why** + **How to apply**. Append-only, no state machine. |
| `build.md` | How the work executes: build mode, migration strategy, gotchas, rollout. |
| `domain-model.md` | Information architecture — entities, relationships, cardinalities, state ownership. |
| `tech.md` | Stack choices, seeded from harness rules; deviations recorded with whys. |
| `doctrine` / `glossary` / `non-goals` / `backlog` / `rejected` / `references` / `milestones` | As their templates describe. |

The complexity dial sets *defaults*, not a cage — any lazy pillar materializes the moment the conversation produces content for it.

---

## Build modes (replacing the greenfield doctrine)

v1 applied a present-tense "greenfield" writing doctrine unconditionally — which was a bug for brownfield work, where migration vocabulary is load-bearing. v2 folds this into `build.md` as a **mode** chosen at intake:

- **greenfield** (default) — present-tense everywhere, no phantom history. Execution sections closed.
- **brownfield** — migration vocabulary is legitimate in `build.md`; other pillars still describe the target.
- **hybrid** — new surface on a live system; execution sections apply to the seams only.

`build.md` also captures **gotchas** — execution hazards known now, before plan mode, because surfacing them in plan mode is too late.

---

## Harvest (optional)

By default the session folder *is* the product — self-contained, resumed by the next `/brainstorm start`. When the repo is v9-harnessed (`docs/architecture/` + `docs/modules/` exist) the skill *offers* the harvest adapter at `stop`, which routes pillars into the doc tree (ADRs, module pillars, plans, the `boundary` skill). See `harvest.md`. The adapter is never assumed.

---

## Hard rules

1. **No production code outside the session folder.** Illustrative snippets are fine inside it.
2. **Speak English to the user; codes (`Q3`, `D7`) live in the files.**
3. **`AskUserQuestion` appears in exactly three places:** the intake frame, interview mode, converge picks.
4. **Suggested, never seized** — mode shifts, abstractions, probes are offered once.
5. **Questions are the only convergence currency** — nothing pending may live only in the transcript.
6. **No auto-invocation** — only `/brainstorm start` and `/brainstorm stop`.

---

## Files

```
brainstorm/
├── SKILL.md      # the skill definition Claude Code loads (~1.8k words)
├── README.md     # this file
├── harvest.md    # optional v9 doc-tree adapter
└── templates/    # pillar templates copied into the session folder on first use
```
