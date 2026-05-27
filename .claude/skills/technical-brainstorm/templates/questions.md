# Open Questions

This file is the **live ledger of unresolved concerns and pending decisions**. Every open design question or worry lives here, and only here — plan docs never host their own questions, they link back to this file with the relevant Q-numbers.

Each question is **self-contained**: full text, optional options, optional lean, and where the resolution lands. You should be able to read any question and understand it without opening another doc. Duplicating one paragraph of context is much cheaper than the cognitive cost of context-switching.

**In Explore mode**, questions land here in the user's framing — possibly just a concern stated in prose, without Options or Lean. That is fine. Captured concerns are valid questions even when their shape is fuzzy. Resist the urge to immediately structure them into A/B/C/D choices; that happens when the user invites decide-mode for a specific question.

When a question transitions through a decision flow:
1. User signals "let's resolve Q-N" → enter decide mode for this Q.
2. Decision lands in `decisions.md` with `STATUS: tentative`. **The question stays here**, in a tentatively-answered state (cross-reference the D-N).
3. User says "commit D-N" → the question is **deleted** from this file. No strikethrough, no "(resolved)" marker.
4. User says "rescind D-N" before commit → the question stays, the decision is marked rescinded.

When you add a new question, fill in fields the user has actually given you. Leave others blank. The dependency graph (`Blocks.` field) is computed only when the user moves into decide mode and needs sequencing.

---

## Conventions

**Group questions by domain** when the list grows past ~10 entries. Use `## Category` headers (e.g. `## Data & Schema`, `## Runtime`, `## Connectors`). Categories are project-specific.

**Question ID** is `QN` where N is the next free integer. IDs are stable for as long as the question is open. On commit-delete, the ID disappears with the question — do not reuse it.

**Question body fields** (per entry):

- **Question.** Full prose, may be multi-paragraph. Repeat context if needed. Use the user's words when capturing in Explore mode.
- **Options.** *(optional)* Lettered list (A / B / C ...) with one-line description per option. Add only when the user has named alternatives, or when entering decide mode for this question.
- **Lean.** *(optional)* The user's current preference, one line. Drop the field entirely if no lean exists yet — don't write "none yet". This field reflects the user's lean, not the skill's.
- **Claude's take.** *(optional, OPT-IN ONLY)* The skill's recommendation. **Default: do not write this field.** Emit only when the user explicitly asks "what would you recommend?" / "what's your take?" / similar on this specific question. Phrase as a clear pick + one-line reason. If the field becomes stale (options change, scope shifts), delete it.
- **Tentatively answered by.** *(only when a tentative D-N exists)* Cross-reference to `decisions.md`. Marks the question as in-flight rather than fully open.
- **Resolution lands in.** *(optional)* Target doc + section (e.g. `04-runtime.md §3.2`). Tells the resolver where to absorb the answer.
- **Blocks.** *(optional)* Milestone (`M0`) or other Q-numbers (`Q5, Q7`) that depend on this. Empty = "nothing yet".

**Extension sections** beyond plain questions are allowed:

- `## Upstream feature requests` — items that aren't questions we own; they're features we need from upstream services. Use IDs like `U-foo-1`.
- `## Doc completeness follow-ups` — work items that aren't decisions but should not be forgotten. Use IDs like `F1`, `F2`.

Resolved upstream-feature items and completed follow-ups get **deleted**, same rule as questions.

---

## Q1 — [Title]

**Question.** [Full text. Repeat context if needed — a future reader should be able to read this without leaving the doc. In Explore mode, capture in the user's words.]

**Options.** *(optional — only when named by the user or entering decide mode)*
- A. [Option A — what it means in one line]
- B. [Option B]
- C. [Option C]

**Lean.** *(optional, user's lean)*

**Tentatively answered by.** *(only if a tentative D-N exists)*

**Resolution lands in.** *(optional)* `XX-foo.md` §N

**Blocks.** *(optional)* [Milestone (e.g., M0) or other Q-numbers.]

---

## Q2 — [Title]

(same format)

---

## Upstream feature requests *(optional section)*

### U-foo-1 — [Title]

[What we want from the upstream service.]

**Why we want it.** [Reason — usually a current workaround that's costing us something.]

[Current status: filed, tracked, ETA, etc.]

---

## Doc completeness follow-ups *(optional section)*

- **F1** — [Doc name + one-line scope]. [What triggers writing it.] [Which milestone it must precede.]
- **F2** — [Doc name + one-line scope]. [What triggers writing it.] [Which milestone it must precede.]
