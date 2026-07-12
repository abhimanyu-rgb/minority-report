# Build

This pillar holds **how the work gets executed** — decided during brainstorming, not deferred to plan mode. Migration constraints and execution gotchas discovered late invalidate designs; surfacing them here, while the design is still fluid, is the point.

At `start` the skill asks: *"Is this greenfield, or are we changing something that exists?"* The answer sets **Mode** below and opens or closes the execution sections. The sync agent treats this file as a contradiction source — a decision that implies migration work with no entry here raises a question.

## Mode

`greenfield` *(default)* | `brownfield` | `hybrid`

- **greenfield** — nothing built yet: no production deploys, no users, no legacy code. The execution sections below are closed — mark them *Not applicable (greenfield)*. **Writing posture:** all pillars describe the system as it *will be*, in present tense, as though the chosen design was always the plan. Banned: "replaces" / "supersedes" / "previously" / "formerly" / "no longer" / "originally proposed" / `~~strikethrough~~` / "(resolved)" markers — the reader has no past, so don't reference one. Past tense lives only in `decisions.md`, `rejected.md`, `references.md`, and git history.
- **brownfield** — the idea changes a system that already exists. All sections below are live, and migration vocabulary — "replaces", "currently", "migrate from" — is legitimate and load-bearing **in this file**. Other pillars still describe the *target* state in present tense; the journey from here to there lives here.
- **hybrid** — a new surface attached to a live system (a new module in a shipping product). The sections below apply to the seams only: integration points, shared state, contract changes. The new surface itself follows greenfield posture.

## Current state

*(brownfield/hybrid)* What exists today, as relevant to the change. Link code paths or docs rather than restating them.

## Target state

One or two orienting sentences — cross-reference `thesis.md` rather than duplicating it.

## Migration strategy

How we get from current to target: phases, order of operations, coexistence windows, rollback points. Harvest routes this section into the implementation plan.

## Gotchas

Execution hazards known *now*, before plan mode — each one a bullet with why it bites:

- [e.g. data backfill must run before the new index exists, or reads 404 during the window]
- [e.g. auth cutover can't be phased — sessions are shared, it's all-or-nothing]
- [e.g. the event consumer is not idempotent; dual-write window will double-process]

## Rollout & risks

Sequencing, feature flags, kill switches, and the failure modes each phase accepts.
