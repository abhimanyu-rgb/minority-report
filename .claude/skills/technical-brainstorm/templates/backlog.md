# Backlog

This file is the **forward-looking list of deferred-but-planned items** — work the team intends to build, but not in the current scope. It complements `non-goals.md` (which holds the scope-creep guards: things we are **not** building) and `rejected.md` (which holds paths we considered and chose against). Use the right pillar:

| Pillar | Semantics |
|---|---|
| `backlog.md` (this file) | "We **will** build this, just **later**." Deferred to a known future milestone. Roadmap forward. |
| `non-goals.md` | "We deliberately are **not** building this." Scope guard. May never be built. |
| `rejected.md` | "We considered this path and chose another." Past-tense alternative. |

If you can't tell which file an item belongs in, ask: *"Is the plan to build this eventually?"* If yes → backlog. If no but could change → non-goals. If we already weighed it against an alternative → rejected.

Backlog items carry four load-bearing fields. **Target milestone** names the future bucket (`v1.1`, `M2`, `TBD`); **Why deferred** explains the reason it isn't in the current scope (commonly: scope cut, depends on something else, waiting for user feedback, lower priority than current work); **Scope** sketches what the item actually includes — enough that a future planner can pick it up cold; **Re-evaluate when** is the trigger that promotes it from backlog to active work.

When a backlog item is promoted (its milestone comes due), **delete it from this file** and either (a) seed a new round of intake questions in `questions.md` for the new scope, or (b) move the spec into a plan doc if the design is already mostly clear. Don't strikethrough, don't leave a "(promoted)" marker — same hygiene as resolved questions and triggered non-goals.

If a backlog item turns out to be unworkable or unneeded, move it to `rejected.md` (not deleted silently) with the reason.

---

## B1 — [Title]

**Target milestone.** [v1.1 / M2 / TBD]

**Why deferred.** [The reason it isn't in current scope. Be specific: "scope cut to ship M0 by Q3"; "depends on X landing first"; "waiting for user feedback on whether this is actually needed"; "lower priority than the M0 critical path".]

**Scope.** [What this item actually includes when it eventually gets built. Sketch enough that a future planner can pick it up cold. Bullet points are fine.]

**Depends on.** [Optional. Other backlog items, milestones, or upstream features that need to land first. Drop the field if nothing.]

**Re-evaluate when.** [The trigger that promotes this from backlog to active work. Tie to a milestone boundary, a metric, or an external event.]

---

## B2 — [Title]

(same format)

---
