# Milestones

This file holds **sequencing only** — what ships in what order, with the dependencies that justify the order. Scope of each milestone lives in the plan docs; this file is the schedule.

Every milestone names three things: a **Goal** (one line — what this milestone proves or unlocks), **Depends on** (the prior milestones, or "nothing" for M0), and **Open questions** (Q-numbers from `questions.md` that must be resolved before this milestone can start). The open-questions list is what makes a milestone "ready to start" — when the list is empty, the milestone is unblocked.

The **Ships** field captures the concrete artifact: "auth + empty dashboard deployed to staging" is useful; "MVP foundation" is not. Concrete ship definitions make it visible when a milestone has crept.

Order matters and the order is enforced by `Depends on`. If you ever notice that M3 could ship before M2, the sequencing is wrong — fix it here. Milestones do not exist to chunk work into nice-sized bites; they exist to make dependency order explicit so the team can parallelize what's parallelizable and serialize what isn't.

When a milestone ships, do **not** mark it "complete" with a strikethrough or "(shipped)" marker. The plan docs for that milestone should already describe the steady state in present tense; the milestone entry stays here as schedule, not as history. (Git tags and PR history capture "what shipped when" — this file is forward-looking.)

---

## M0 — [Name]

**Goal.** [One-line — what this milestone proves or unlocks.]

**Depends on.** Nothing (this is the start).

**Open questions.** Q1, Q2, Q3 — see `questions.md`.

**Ships.** [Concrete deployed artifact.]

---

## M1 — [Name]

**Goal.** [One-line.]

**Depends on.** M0.

**Open questions.** Q4, Q5 — see `questions.md`.

**Ships.** [Concrete deployed artifact.]

---

## M2 — [Name]

(same format)

---
