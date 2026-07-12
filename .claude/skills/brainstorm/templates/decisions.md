# Decisions

This file is the **append-only ledger of resolved decisions**, with the reasoning future-you needs to judge edge cases.

Load-bearing fields:

- **Decision** — what was decided, in one or two sentences.
- **Why** — the motivation: a constraint, an incident, a deadline, a stakeholder ask. Without the *why*, decisions decay into rules no one understands.
- **How to apply** — when and where this decision shapes future work. Name the files, layers, or situations where it kicks in.

There is no tentative/committed state machine. A decision is a decision the moment it's written; the next sync handles its ripples. **Reversing** a decision = append a new decision that names what it reverses, add a one-line `Reversed by D-M (YYYY-MM-DD)` note to the old entry, and let the sync raise questions for anything downstream.

This ledger is one of the places where past tense is permitted (with `rejected.md`, `references.md`, `build.md`'s execution sections, and git history).

---

## D1 — [Title]

**Decision.** [What was decided.]

**Why.** [The motivation future-you needs.]

**How to apply.** [Where this rule kicks in — be specific.]

**Resolves.** Q1 (deleted from `questions.md`).

**Alternatives considered.** *(optional — reference `rejected.md` if substantial)*

**Reverses.** *(only when this decision reverses an earlier one — name it and say what changed)*
