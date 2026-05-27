# Decisions

This file is the **append-only ledger of resolved decisions**. Every decision the brainstorm produces lands here, with the reasoning that future-you will need to judge edge cases.

Each entry has these load-bearing fields:

- **Status** — `tentative | committed | rescinded`. New decisions land as `tentative` (no cascade dispatched, question stays open in `questions.md`). User explicitly says "commit" to lock in (cascade fires, question deletes). User explicitly says "rescind" to reverse (cascade reversals if previously committed, question restored if needed).
- **Decision** — what was decided, in one or two sentences.
- **Why** — the motivation: a past incident, a constraint, a deadline, a stakeholder ask. Without the *why*, decisions decay into rules no one understands.
- **How to apply** — when and where this decision should shape future work. Without it, decisions get ignored at the boundaries where they matter most.

This file is **append-only**. If a decision is reversed, mark it `STATUS: rescinded` with the reason — do not delete the entry. The ledger is a record of what was true (or proposed) when it was written. It is one of the four places inside the brainstorm folder where past tense is permitted (the others: `rejected.md`, `references.md`, git history).

When a question in `questions.md` is resolved, the question is **NOT** immediately deleted — it is marked tentatively-answered (referenced by the new decision's `Resolves Q-N` field). The question is deleted only when the decision transitions to `committed`. This gives the user space to reverse a tentative call without restoring text by hand.

---

## D1 — [Title]

**Status.** tentative

**Decision.** [What was decided, in one or two sentences.]

**Why.** [The motivation — past incident, constraint, deadline, stakeholder ask. The reason future-you needs to judge edge cases.]

**How to apply.** [When and where this decision shapes future work. Be specific — name the files, layers, or situations where this rule kicks in.]

**Resolves.** Q1 (deleted from `questions.md` on commit).

**Alternatives considered.** [Optional. Reference `rejected.md` entries if substantial. Skip if obvious.]

**Committed on.** [YYYY-MM-DD — filled when STATUS transitions to committed. Omit until then.]

**Rescinded on.** [YYYY-MM-DD with one-line reason — filled when STATUS transitions to rescinded. Omit until then.]

---

## D2 — [Title]

(same format)

---
