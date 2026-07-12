# Open Questions

This file is the **single convergence currency** of the session. Every unresolved design call lives here and only here — whether the user raised it, the sync agent found it, or a probe surfaced it. Plan docs and pillars never host their own questions; they link back here.

The session is **coherent** exactly when this file is empty after a fresh sync. That makes hygiene load-bearing:

- Every entry must be **closeable** — the `Closes when.` field says what resolution looks like. Vague musings are not questions; distill them until they're closeable or leave them in the conversation.
- Only **design-calls** belong here — items whose resolution changes the idea. Editorial bookkeeping is the sync agent's job, applied directly and noted in its report.
- A resolved question is **deleted** (its decision lives in `decisions.md`). A parked question is deleted too, with an explicit entry in `backlog.md` or `non-goals.md`. No strikethrough, no "(resolved)" markers.

Each question is **self-contained**: full text in the user's framing, readable without opening another doc. Group under `## Category` headers when the list grows past ~10.

IDs are `QN`, stable while open, never reused after deletion.

---

## Q1 — [Title in the user's words]

**Question.** [Full prose — paraphrase what the user said, or state the contradiction/gap the sync found. Repeat context; a future reader should need nothing else.]

**Raised by.** user | sync | probe

**Closes when.** [What resolution looks like — a pick between options, a confirmed fact, an accepted risk.]

**Options.** *(optional — only when named by the user or entering converge)*
- A. [one line]
- B. [one line]

**Lean.** *(optional — the user's lean, never the skill's)*

**Claude's take.** *(opt-in only — write only when the user asks for a recommendation on this question; delete if it goes stale)*

**Resolution lands in.** *(optional)* [pillar or doc + section]

**Blocks.** *(optional)* [milestone or other Q-numbers]
